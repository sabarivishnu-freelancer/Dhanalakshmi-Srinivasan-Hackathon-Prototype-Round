import os
import io
import threading
from flask import Flask, render_template, request, redirect, session, jsonify, send_file
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from ai_agent import analyze_petition, find_similar
from reportlab.pdfgen import canvas
from dotenv import load_dotenv
from mailer import send_email

load_dotenv()

DB_NAME = os.getenv("DB_NAME", "petitiondb")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "vish")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT)
cur = conn.cursor()


def login_required(role=None):
    def wrapper(fn):
        from functools import wraps

        @wraps(fn)
        def decorated(*args, **kwargs):
            if not session.get("user_id"):
                return redirect("/")
            if role and session.get("role") != role:
                return redirect("/")
            return fn(*args, **kwargs)

        return decorated

    return wrapper


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form.get("email")
        password = request.form["password"]
        role = request.form.get("role", "student")
        if not username or not password:
            return render_template("register.html", error="Missing fields")

        # prevent duplicate users by username or email
        cur.execute(
            "SELECT id FROM users WHERE username=%s OR (email IS NOT NULL AND lower(email)=lower(%s))",
            (username, email),
        )
        if cur.fetchone():
            return render_template("register.html", error="Username or email already in use")

        hashed = generate_password_hash(password)
        try:
            cur.execute("INSERT INTO users (username,password,email,role) VALUES (%s,%s,%s,%s)", (username, hashed, email, role))
            conn.commit()
        except Exception as e:
            conn.rollback()
            # even though we already checked, catch unique constraint errors gracefully
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                return render_template("register.html", error="Username or email already in use")
            return render_template("register.html", error=str(e))

        return redirect("/")

    return render_template("register.html")


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"].strip()
        p = request.form["password"]
        cur.execute("SELECT id,password,role FROM users WHERE username=%s", (u,))
        user = cur.fetchone()
        if user and check_password_hash(user[1], p):
            session["user_id"] = user[0]
            session["role"] = user[2]
            return redirect("/student" if user[2] == "student" else "/admin")
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/student", methods=["GET", "POST"])
@login_required(role="student")
def student():
    if request.method == "POST":
        title = request.form["title"].strip()
        desc = request.form["description"].strip()

        # exact duplicate prevention (compare against all petitions, not just user's)
        cur.execute(
            "SELECT id, title, description, student_id FROM petitions"
        )
        existing = cur.fetchall()

        # first try exact match (case insensitive)
        for pid, etitle, edesc, owner_id in existing:
            if etitle.lower() == title.lower() and edesc.lower() == desc.lower():
                cur.execute(
                    "SELECT id,title,description,category,"
                    "CASE WHEN signature_count>10 THEN 'High' "
                    "WHEN signature_count>5 THEN 'Moderate' ELSE 'Low' END as priority,"
                    "status,created_at "
                    "FROM petitions WHERE student_id=%s ORDER BY created_at DESC",
                    (session["user_id"],),
                )
                rows = cur.fetchall()
                # decide on message based on ownership
                if owner_id == session["user_id"]:
                    msg = "You have already submitted an identical petition"
                else:
                    msg = "A petition with identical title and description already exists"
                return render_template("student.html", petitions=rows, error=msg)

        # next, NLP-based similarity check using TF-IDF cosine similarity across all descriptions
        desc_list = [edesc for (_, _, edesc, _) in existing]
        sim_text, sim_score = find_similar(desc, desc_list, threshold=0.7)
        if sim_text:
            cur.execute(
                "SELECT id,title,description,category,"
                "CASE WHEN signature_count>10 THEN 'High' "
                "WHEN signature_count>5 THEN 'Moderate' ELSE 'Low' END as priority,"
                "status,created_at "
                "FROM petitions WHERE student_id=%s ORDER BY created_at DESC",
                (session["user_id"],),
            )
            rows = cur.fetchall()
            return render_template("student.html", petitions=rows,
                error=f"A similar petition already exists (score {sim_score:.2f})")

        # analyze_petition may return 2 or 4 values (legacy support)
        res = analyze_petition(desc)
        if isinstance(res, tuple) and len(res) == 4:
            cat, pri, reason, confidence = res
        else:
            cat, pri = res
            reason, confidence = None, None
        try:
            cur.execute(
                "INSERT INTO petitions (title,description,category,priority,student_id) VALUES (%s,%s,%s,%s,%s)",
                (title, desc, cat, pri, session["user_id"]),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            # catch unique index violation just in case
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                pass  # already handled above, but safe fallback
            else:
                return render_template("student.html", error=str(e))

    cur.execute("SELECT id,title,description,category,"
                "CASE WHEN signature_count>10 THEN 'High' "
                "WHEN signature_count>5 THEN 'Moderate' ELSE 'Low' END as priority,"
                "status,created_at FROM petitions WHERE student_id=%s ORDER BY created_at DESC", (session["user_id"],))
    rows = cur.fetchall()
    return render_template("student.html", petitions=rows)


@app.route("/admin")
@login_required(role="admin")
def admin():
    cur.execute("SELECT id,title,description,category,"
                "CASE WHEN signature_count>10 THEN 'High' "
                "WHEN signature_count>5 THEN 'Moderate' ELSE 'Low' END as priority,"
                "status,signature_count,student_id,created_at FROM petitions "
                "ORDER BY signature_count DESC, created_at DESC")
    rows = cur.fetchall()
    return render_template("admin.html", petitions=rows)


@app.route("/analytics")
@login_required(role="admin")
def analytics():
    """Display petition trend analytics and status distribution"""
    return render_template("analytics.html")


@app.route("/api/analytics/trending")
@login_required(role="admin")
def api_trending_petitions():
    """Get trending petitions (top 10 by signature count with recent activity)"""
    try:
        cur.execute("""
            SELECT id, title, description, category, signature_count, status, created_at
            FROM petitions
            ORDER BY signature_count DESC, created_at DESC
            LIMIT 10
        """)
        petitions = cur.fetchall()
        
        data = []
        for p in petitions:
            # Get signature growth in last 7 days (count of signatures added in past week)
            cur.execute("""
                SELECT COUNT(*) FROM signatures 
                WHERE petition_id=%s AND signed_at >= NOW() - INTERVAL '7 days'
            """, (p[0],))
            week_growth = cur.fetchone()[0]
            
            data.append({
                "id": p[0],
                "title": p[1],
                "description": p[2],
                "category": p[3],
                "signature_count": p[4],
                "week_growth": week_growth,
                "status": p[5],
                "created_at": str(p[6]),
                "growth_rate": "📈 Growing" if week_growth > 0 else "📊 Stable"
            })
        
        return jsonify({"success": True, "trending": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/analytics/status-distribution")
@login_required(role="admin")
def api_status_distribution():
    """Get breakdown of petitions by status"""
    try:
        cur.execute("""
            SELECT status, COUNT(*) as count
            FROM petitions
            GROUP BY status
        """)
        results = cur.fetchall()
        
        status_dist = {
            "Pending": 0,
            "Approved": 0,
            "Rejected": 0
        }
        
        for status, count in results:
            if status in status_dist:
                status_dist[status] = count
        
        # Get total petitions
        total = sum(status_dist.values())
        
        # Calculate percentages
        percent_data = {
            status: round((count / total * 100) if total > 0 else 0, 1)
            for status, count in status_dist.items()
        }
        
        return jsonify({
            "success": True,
            "distribution": status_dist,
            "percentages": percent_data,
            "total": total
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/analytics/category-breakdown")
@login_required(role="admin")
def api_category_breakdown():
    """Get petition distribution by category"""
    try:
        cur.execute("""
            SELECT category, COUNT(*) as count, SUM(signature_count) as total_signatures
            FROM petitions
            GROUP BY category
            ORDER BY total_signatures DESC
        """)
        results = cur.fetchall()
        
        data = []
        for category, count, total_sigs in results:
            data.append({
                "category": category or "Uncategorized",
                "petition_count": count,
                "total_signatures": total_sigs or 0,
                "avg_signatures": round((total_sigs or 0) / count, 1) if count > 0 else 0
            })
        
        return jsonify({"success": True, "categories": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/analytics/summary")
@login_required(role="admin")
def api_analytics_summary():
    """Get high-level summary statistics"""
    try:
        # Total petitions
        cur.execute("SELECT COUNT(*) FROM petitions")
        total_petitions = cur.fetchone()[0]
        
        # Total signatures
        cur.execute("SELECT SUM(signature_count) FROM petitions")
        total_signatures = cur.fetchone()[0] or 0
        
        # Total users
        cur.execute("SELECT COUNT(*) FROM users WHERE role='student'")
        total_students = cur.fetchone()[0]
        
        # Average signatures per petition
        avg_signatures = round(total_signatures / total_petitions, 1) if total_petitions > 0 else 0
        
        # Most popular category
        cur.execute("""
            SELECT category, COUNT(*) as count
            FROM petitions
            GROUP BY category
            ORDER BY count DESC
            LIMIT 1
        """)
        most_popular = cur.fetchone()
        popular_category = most_popular[0] if most_popular else "N/A"
        
        return jsonify({
            "success": True,
            "total_petitions": total_petitions,
            "total_signatures": total_signatures,
            "total_students": total_students,
            "avg_signatures_per_petition": avg_signatures,
            "most_popular_category": popular_category
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/update/<int:id>/<status>")
@login_required(role="admin")
def update(id, status):
    if status not in ("Approved", "Rejected", "Pending"):
        status = "Pending"
    cur.execute("UPDATE petitions SET status=%s WHERE id=%s", (status, id))
    conn.commit()
    # schedule removal if rejected
    if status == "Rejected":
        def delete_later(petition_id):
            try:
                cur.execute("DELETE FROM petitions WHERE id=%s", (petition_id,))
                conn.commit()
            except Exception:
                conn.rollback()
        timer = threading.Timer(120, delete_later, args=(id,))
        timer.daemon = True
        timer.start()
    # notify petition creator by email (if available)
    cur.execute(
        "SELECT u.email, u.username, p.title FROM users u JOIN petitions p ON u.id=p.student_id WHERE p.id=%s",
        (id,),
    )
    row = cur.fetchone()
    if row and row[0]:
        to_email = row[0]
        student_name = row[1]
        petition_title = row[2]
        subject = f"Your petition '{petition_title}' status updated"
        body = f"Hello {student_name},\n\nYour petition '{petition_title}' has been marked as: {status}.\n\nRegards,\nPetition System"
        try:
            send_email(subject, body, to_email)
        except Exception:
            pass

    # notify all users who signed this petition
    cur.execute(
        "SELECT u.email, u.username FROM signatures s "
        "JOIN users u ON u.id=s.user_id "
        "WHERE s.petition_id=%s AND u.email IS NOT NULL",
        (id,),
    )
    signers = cur.fetchall()
    if signers:
        # reuse the subject/body or adjust for signers
        subject2 = f"Update on petition '{petition_title}' you signed"
        body2 = f"Hello,\n\nThe petition '{petition_title}' that you signed has been marked as: {status}.\n\nRegards,\nPetition System"
        for email, uname in signers:
            try:
                send_email(subject2, body2, email)
            except Exception:
                pass
    return redirect("/admin")


@app.route("/export/json")
@login_required(role="admin")
def export_json():
    cur.execute("SELECT id,title,description,category,"
                "CASE WHEN signature_count>10 THEN 'High' "
                "WHEN signature_count>5 THEN 'Moderate' ELSE 'Low' END as priority,"
                "status,signature_count,student_id,created_at FROM petitions ORDER BY signature_count DESC")
    rows = cur.fetchall()
    data = []
    for r in rows:
        data.append({
            "id": r[0],
            "title": r[1],
            "description": r[2],
            "category": r[3],
            "priority": r[4],
            "status": r[5],
            "signature_count": r[6],
            "student_id": r[7],
            "created_at": str(r[8]),
        })
    return jsonify(data)


@app.route("/export/pdf")
@login_required(role="admin")
def export_pdf():
    cur.execute("SELECT id,title,description,category,"
                "CASE WHEN signature_count>10 THEN 'High' "
                "WHEN signature_count>5 THEN 'Moderate' ELSE 'Low' END as priority,"
                "status,signature_count,created_at FROM petitions ORDER BY signature_count DESC")
    rows = cur.fetchall()
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 800
    pdf.setFont("Helvetica-Bold", 12)
    
    # Header
    pdf.drawString(40, y, "Petition Report")
    y -= 20
    pdf.setFont("Helvetica", 10)
    
    for r in rows:
        petition_id = r[0]
        title = r[1]
        description = r[2]
        category = r[3]
        priority = r[4]
        status = r[5]
        signature_count = r[6]
        created_at = str(r[7])
        
        # Title line
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(40, y, f"ID: {petition_id} | Title: {title}")
        y -= 15
        
        # Description with wrapping
        pdf.setFont("Helvetica", 9)
        max_width = 500
        words = description.split()
        line = ""
        
        for word in words:
            test_line = line + word + " "
            if pdf.stringWidth(test_line) > max_width:
                if line:
                    pdf.drawString(50, y, line.strip())
                    y -= 12
                line = word + " "
            else:
                line = test_line
        
        if line:
            pdf.drawString(50, y, line.strip())
            y -= 12
        
        # Details line
        pdf.setFont("Helvetica", 9)
        details = f"Category: {category} | Priority: {priority} | Status: {status} | Signatures: {signature_count} | Created: {created_at}"
        pdf.drawString(50, y, details)
        y -= 20
        
        # Page break if needed
        if y < 60:
            pdf.showPage()
            y = 800
            pdf.setFont("Helvetica", 10)

    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="petitions.pdf", mimetype="application/pdf")


@app.route("/browse")
@login_required(role="student")
def browse():
    """Browse and sign all petitions, sorted by priority and signature count"""
    cur.execute("""
        SELECT id, title, description, category,
            CASE WHEN signature_count>10 THEN 'High'
                 WHEN signature_count>5 THEN 'Moderate' ELSE 'Low' END as priority, status, signature_count, student_id, created_at
        FROM petitions
        ORDER BY signature_count DESC, created_at DESC
    """)
    rows = cur.fetchall()
    
    # Get user's signatures
    cur.execute("SELECT petition_id FROM signatures WHERE user_id=%s", (session["user_id"],))
    signed_ids = set(item[0] for item in cur.fetchall())
    
    return render_template("browse.html", petitions=rows, signed_ids=signed_ids)


@app.route("/sign/<int:petition_id>", methods=["POST"])
@login_required(role="student")
def sign_petition(petition_id):
    """Digitally sign a petition and increment signature count"""
    user_id = session["user_id"]
    
    try:
        # try to insert a new signature; unique index prevents duplicates
        cur.execute(
            """
            INSERT INTO signatures (petition_id, user_id)
            VALUES (%s, %s)
            ON CONFLICT (petition_id, user_id) DO NOTHING
            """,
            (petition_id, user_id)
        )

        # if nothing was inserted, the user had already signed
        if cur.rowcount == 0:
            return jsonify({"success": False, "message": "You have already signed this petition"}), 400

        # increment signature counter only when a row was added
        cur.execute(
            "UPDATE petitions SET signature_count = signature_count + 1 WHERE id=%s",
            (petition_id,)
        )
        conn.commit()

        # return the new count
        cur.execute("SELECT signature_count FROM petitions WHERE id=%s", (petition_id,))
        result = cur.fetchone()
        new_count = result[0] if result else 0

        return jsonify({"success": True, "message": "Petition signed!", "signature_count": new_count})
    except Exception as e:
        conn.rollback()
        # catch uniqueness errors or other db issues
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/petition/<int:petition_id>/status")
@login_required(role="student")
def petition_status(petition_id):
    """Get live petition status and signature count"""
    try:
        cur.execute(
            "SELECT id, title, status, signature_count, "
        "CASE WHEN signature_count>10 THEN 'High' "
        "WHEN signature_count>5 THEN 'Moderate' ELSE 'Low' END as priority, category FROM petitions WHERE id=%s",
            (petition_id,)
        )
        petition = cur.fetchone()
        
        if not petition:
            return jsonify({"success": False, "message": "Petition not found"}), 404
        
        # Check if user has signed
        cur.execute(
            "SELECT id FROM signatures WHERE petition_id=%s AND user_id=%s",
            (petition_id, session["user_id"])
        )
        is_signed = cur.fetchone() is not None
        
        return jsonify({
            "success": True,
            "id": petition[0],
            "title": petition[1],
            "status": petition[2],
            "signature_count": petition[3],
            "priority": petition[4],
            "category": petition[5],
            "is_signed": is_signed
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/petitions/live")
@login_required(role="student")
def petitions_live():
    """Get all petitions with live data for real-time updates"""
    try:
        cur.execute("""
            SELECT id, title, description, category,
                CASE WHEN signature_count>10 THEN 'High'
                     WHEN signature_count>5 THEN 'Moderate' ELSE 'Low' END as priority,
                status, signature_count, created_at
            FROM petitions
            ORDER BY signature_count DESC
        """)
        petitions = cur.fetchall()
        
        data = []
        for p in petitions:
            data.append({
                "id": p[0],
                "title": p[1],
                "description": p[2],
                "category": p[3],
                "priority": p[4],
                "status": p[5],
                "signature_count": p[6],
                "created_at": str(p[7])
            })
        
        return jsonify({"success": True, "petitions": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
