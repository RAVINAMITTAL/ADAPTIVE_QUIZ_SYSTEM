from dotenv import load_dotenv
load_dotenv()

from datetime import datetime

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
)
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from models import (
    db, 
    User, 
    Question, 
    QuizAttempt, 
    AttemptQuestion,
    UserStreak,           # ← ADD
    Achievement,          # ← ADD
    UserAchievement,      # ← ADD
    WeeklyGoal            # ← ADD
)

from ai_engine import generate_mcqs, get_suggested_topics
from ml_engine import get_next_difficulty, DIFFICULTY_LEVELS
from sqlalchemy import func


# ---------------- APP & EXTENSIONS ----------------

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

mail = Mail(app)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------- AUTH (Module 1) ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
            return redirect(url_for("register"))

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            is_admin=False,
        )
        db.session.add(user)
        db.session.commit()
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


# ---------------- DASHBOARD (Modules 2–5) ----------------

@app.route("/")
@login_required
def dashboard():
    from datetime import date, timedelta  # ← ADD THIS
    
    attempts = (
        QuizAttempt.query.filter_by(user_id=current_user.id)
        .order_by(QuizAttempt.started_at.desc())
        .limit(10)
        .all()
    )

    topic_stats = (
        db.session.query(
            QuizAttempt.topic,
            func.avg(QuizAttempt.score / QuizAttempt.total_questions),
            func.count(QuizAttempt.id),
        )
        .filter(QuizAttempt.user_id == current_user.id)
        .group_by(QuizAttempt.topic)
        .all()
    )

    time_stats = (
        db.session.query(
            QuizAttempt.started_at,
            QuizAttempt.score,
            QuizAttempt.total_questions,
        )
        .filter(QuizAttempt.user_id == current_user.id)
        .order_by(QuizAttempt.started_at)
        .all()
    )

    # Get user's streak
    streak = UserStreak.query.filter_by(user_id=current_user.id).first()
    current_streak = streak.current_streak if streak else 0
    longest_streak = streak.longest_streak if streak else 0

    # Get weekly goal for current week
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    weekly_goal = WeeklyGoal.query.filter_by(
        user_id=current_user.id,
        week_start=week_start
    ).first()

    return render_template(
        "dashboard.html",
        attempts=attempts,
        topic_stats=topic_stats,
        time_stats=time_stats,
        current_streak=current_streak,      # ← ADD
        longest_streak=longest_streak,      # ← ADD
        weekly_goal=weekly_goal             # ← ADD
    )


# ---------------- QUIZ + LLM + ML (Modules 2–4) ----------------

@app.route("/quiz/new", methods=["GET", "POST"])
@login_required
def new_quiz():
    if request.method == "POST":
        topic = request.form["topic"]
        num_questions = int(request.form.get("num_questions", 5))
        difficulty = request.form.get("difficulty") or ""
        model_type = request.form.get("ml_model", "logistic")
        subtopic = request.form.get("subtopic", "").strip()
        session["subtopic"] = subtopic
        # Get user's recent attempts (for ML stats)
        user_attempts = (
            QuizAttempt.query.filter_by(user_id=current_user.id)
            .order_by(QuizAttempt.started_at.desc())
            .limit(20)
            .all()
        )

        # Filter attempts on current topic
        topic_attempts = [a for a in user_attempts if a.topic == topic]

        # Use adaptive ML if there is history AND difficulty is Auto (empty string)
        if topic_attempts and not difficulty:
            last = topic_attempts[0]
            accuracy = (
                last.score / last.total_questions if last.total_questions else 0.5
            )
            avg_time = (
                (last.time_taken_sec or 60) / last.total_questions
                if last.total_questions
                else 30
            )

            # Recent trend (last 3 attempts on this topic)
            recent = topic_attempts[:3]
            if len(recent) >= 2:
                recent_accs = [
                    a.score / a.total_questions for a in recent if a.total_questions
                ]
                recent_trend = recent_accs[0] - recent_accs[-1] if recent_accs else 0
            else:
                recent_trend = 0

            stats = {
                "accuracy": accuracy,
                "avg_time_sec": avg_time,
                "prev_difficulty": last.difficulty,
                "total_attempts": len(topic_attempts),
                "recent_trend": recent_trend,
                "time_consistency": 10.0,
                "user_attempts": [
                    {"topic": a.topic, "score": a.score, "total": a.total_questions}
                    for a in user_attempts
                ],
            }

            adaptive = get_next_difficulty(stats, model_type=model_type)
            difficulty = adaptive["next_difficulty"]

            # Store weak topics / confidence in session if you want to show later
            session["weak_topics"] = adaptive.get("weak_topics", [])
            session["ml_confidence"] = adaptive.get("confidence", {})
            session["ml_model_used"] = adaptive.get("model_used", model_type)

        # If still no difficulty (no history or manual), default to Medium
        if not difficulty:
            difficulty = "Medium"

        # Check cached questions in DB
        existing = (
            Question.query.filter_by(topic=topic, difficulty=difficulty)
            .limit(5)
            .all()
        )

        # If not enough cached questions, generate via LLM
        if len(existing) < 5:
            try:
                existing = generate_mcqs(topic=topic, difficulty=difficulty, n=num_questions,subtopic = subtopic)
            except Exception as e:
                flash(f"Error generating questions: {str(e)}", "danger")
                return redirect(url_for("new_quiz"))
            

        # Create quiz attempt
        attempt = QuizAttempt(
            user_id=current_user.id,
            topic=topic,
            difficulty=difficulty,
            score=0,
            total_questions=len(existing),
            started_at=datetime.utcnow(),
        )
        db.session.add(attempt)
        db.session.commit()

        # Attach questions to attempt
        for q in existing:
            aq = AttemptQuestion(
                attempt_id=attempt.id,
                question_id=getattr(q, "id", None),
                question_text=q.question_text,
                option_a=q.option_a,
                option_b=q.option_b,
                option_c=q.option_c,
                option_d=q.option_d,
                correct_answer=q.correct_answer,
                topic=q.topic,
                difficulty=q.difficulty,
                explanation=q.explanation
            )
            db.session.add(aq)
        db.session.commit()

        return redirect(url_for("take_quiz", attempt_id=attempt.id))

    # GET request – render setup form with topic chips and difficulty options
    suggested_topics = get_suggested_topics()
    return render_template(
        "quiz.html",
        mode="setup",
        suggested_topics=suggested_topics,
        difficulty_levels=DIFFICULTY_LEVELS,
    )

@app.route("/achievements")
@login_required
def achievements():
    all_achievements = Achievement.query.all()
    user_achievements = UserAchievement.query.filter_by(user_id=current_user.id).all()
    earned_ids = [ua.achievement_id for ua in user_achievements]
    
    return render_template(
        "achievements.html",
        all_achievements=all_achievements,
        user_achievements=user_achievements,
        earned_ids=earned_ids
    )

@app.route("/quiz/<int:attempt_id>", methods=["GET", "POST"])
@login_required
def take_quiz(attempt_id):
    attempt = QuizAttempt.query.filter_by(
        id=attempt_id, user_id=current_user.id
    ).first_or_404()
    questions = AttemptQuestion.query.filter_by(attempt_id=attempt.id).all()

    if request.method == "POST":
        # Evaluate answers
        score = 0
        for q in questions:
            ans = request.form.get(f"q_{q.id}")
            q.user_answer = ans
            if ans == q.correct_answer:
                q.is_correct = True
                score += 1
            else:
                q.is_correct = False
        attempt.score = score
        attempt.completed_at = datetime.utcnow()

        # Time taken from front-end
        try:
            attempt.time_taken_sec = int(request.form.get("time_taken_sec", "0"))
        except ValueError:
            attempt.time_taken_sec = None

        db.session.commit()
        
        # Update streak and weekly goal
        update_user_streak(current_user.id)
        update_weekly_goal(current_user.id)
        
        # Check for Perfectionist achievement (100% score)
        if attempt.score == attempt.total_questions:
            perf_ach = Achievement.query.filter_by(
                name="Perfectionist"
            ).first()
            if perf_ach:
                existing = UserAchievement.query.filter_by(
                    user_id=current_user.id,
                    achievement_id=perf_ach.id
                ).first()
                if not existing:
                    user_ach = UserAchievement(
                        user_id=current_user.id,
                        achievement_id=perf_ach.id
                    )
                    db.session.add(user_ach)
                    db.session.commit()
                    flash("🏆 Achievement Unlocked: Perfectionist!", "success")

        # Email results (if mail configured)
        send_result_email(current_user, attempt)

        flash(
            f"Quiz completed. Score: {attempt.score}/{attempt.total_questions}", "success"
        )
        return redirect(url_for("quiz_results", attempt_id=attempt.id))


    # Render quiz with timer
    duration_sec = 5 * 60  # 5 minutes
    return render_template(
        "quiz.html",
        mode="take",
        attempt=attempt,
        questions=questions,
        duration_sec=duration_sec,
    )
@app.route("/quiz/<int:attempt_id>/results")
@login_required
def quiz_results(attempt_id):
    attempt = QuizAttempt.query.filter_by(
        id=attempt_id, user_id=current_user.id
    ).first_or_404()
    
    if not attempt.completed_at:
        flash("Complete the quiz first!", "warning")
        return redirect(url_for("take_quiz", attempt_id=attempt_id))
    
    questions = AttemptQuestion.query.filter_by(attempt_id=attempt.id).all()
    
    # Calculate difficulty breakdown
    difficulty_stats = {}
    for q in questions:
        diff = q.difficulty or "Medium"
        if diff not in difficulty_stats:
            difficulty_stats[diff] = {"correct": 0, "total": 0}
        difficulty_stats[diff]["total"] += 1
        if q.is_correct:
            difficulty_stats[diff]["correct"] += 1
    
    return render_template(
        "results.html",
        attempt=attempt,
        questions=questions,
        difficulty_stats=difficulty_stats
    )
# ---------------- Weekly Streak------------------------
def init_achievements():
    """Initialize predefined achievements if not exists"""
    achievements_data = [
        {
            "name": "First Steps",
            "description": "Complete your first quiz",
            "icon": "bi-star",
            "requirement_type": "total_quizzes",
            "requirement_value": 1,
            "badge_color": "bronze"
        },
        {
            "name": "Quick Learner",
            "description": "Complete 5 quizzes",
            "icon": "bi-lightning",
            "requirement_type": "total_quizzes",
            "requirement_value": 5,
            "badge_color": "bronze"
        },
        {
            "name": "Dedicated Student",
            "description": "Complete 20 quizzes",
            "icon": "bi-book",
            "requirement_type": "total_quizzes",
            "requirement_value": 20,
            "badge_color": "silver"
        },
        {
            "name": "Quiz Master",
            "description": "Complete 50 quizzes",
            "icon": "bi-trophy",
            "requirement_type": "total_quizzes",
            "requirement_value": 50,
            "badge_color": "gold"
        },
        {
            "name": "3-Day Streak",
            "description": "Maintain a 3-day quiz streak",
            "icon": "bi-fire",
            "requirement_type": "streak",
            "requirement_value": 3,
            "badge_color": "bronze"
        },
        {
            "name": "Week Warrior",
            "description": "Maintain a 7-day streak",
            "icon": "bi-fire",
            "requirement_type": "streak",
            "requirement_value": 7,
            "badge_color": "silver"
        },
        {
            "name": "Unstoppable",
            "description": "Maintain a 30-day streak",
            "icon": "bi-fire",
            "requirement_type": "streak",
            "requirement_value": 30,
            "badge_color": "gold"
        },
        {
            "name": "Perfectionist",
            "description": "Score 100% in any quiz",
            "icon": "bi-check-circle",
            "requirement_type": "accuracy",
            "requirement_value": 100,
            "badge_color": "silver"
        }
    ]
    
    for ach_data in achievements_data:
        exists = Achievement.query.filter_by(name=ach_data["name"]).first()
        if not exists:
            achievement = Achievement(**ach_data)
            db.session.add(achievement)
    
    db.session.commit()


# ---------------- PERFORMANCE API (Module 5) ----------------

@app.route("/api/performance")
@login_required
def api_performance():
    topic_stats = (
        db.session.query(
            QuizAttempt.topic,
            func.avg(QuizAttempt.score / QuizAttempt.total_questions),
        )
        .filter(QuizAttempt.user_id == current_user.id)
        .group_by(QuizAttempt.topic)
        .all()
    )

    history = (
        QuizAttempt.query.filter_by(user_id=current_user.id)
        .order_by(QuizAttempt.started_at)
        .all()
    )

    data = {
        "topics": [
            {"topic": t[0], "accuracy": float(t[1]) if t[1] is not None else 0.0}
            for t in topic_stats
        ],
        "history": [
            {
                "date": a.started_at.isoformat(),
                "accuracy": a.score / a.total_questions if a.total_questions else 0.0,
            }
            for a in history
        ],
    }
    return jsonify(data)
#----------- Leadership------------------------------
@app.route("/leaderboard")
@login_required
def leaderboard():
    # Overall leaderboard
    users_stats = db.session.query(
        User.id,
        User.name,
        func.count(QuizAttempt.id).label('total_quizzes'),
        func.avg(QuizAttempt.score / QuizAttempt.total_questions).label('avg_accuracy')
    ).join(QuizAttempt).group_by(User.id).order_by(
        func.avg(QuizAttempt.score / QuizAttempt.total_questions).desc()
    ).limit(10).all()
    
    # Topic-specific leaderboard
    topic_filter = request.args.get('topic', '')
    topic_stats = []
    if topic_filter:
        topic_stats = db.session.query(
            User.id,
            User.name,
            func.count(QuizAttempt.id).label('total_quizzes'),
            func.avg(QuizAttempt.score / QuizAttempt.total_questions).label('avg_accuracy')
        ).join(QuizAttempt).filter(QuizAttempt.topic == topic_filter).group_by(User.id).order_by(
            func.avg(QuizAttempt.score / QuizAttempt.total_questions).desc()
        ).limit(10).all()
    
    # Get available topics
    topics = db.session.query(QuizAttempt.topic).distinct().all()
    topics = [t[0] for t in topics]
    
    # Calculate badges for current user
    user_quiz_count = QuizAttempt.query.filter_by(user_id=current_user.id).count()
    badge = "Bronze" if user_quiz_count >= 5 else None
    if user_quiz_count >= 20:
        badge = "Silver"
    if user_quiz_count >= 50:
        badge = "Gold"
    
    return render_template(
        "leaderboard.html",
        users_stats=users_stats,
        topic_stats=topic_stats,
        topics=topics,
        selected_topic=topic_filter,
        user_badge=badge,
        user_quiz_count=user_quiz_count
    )


# ---------------- EMAIL RESULTS (Module 6) ----------------

def send_result_email(user: User, attempt: QuizAttempt):
    """Send quiz results email (with error handling)"""
    if not app.config.get("MAIL_USERNAME"):
        return
    
    try:
        incorrect = AttemptQuestion.query.filter_by(
            attempt_id=attempt.id, is_correct=False
        ).all()
        weak_topics = list({q.topic for q in incorrect}) if incorrect else []
        recommended_next = attempt.topic

        msg = Message(
            subject=f"Quiz Result - {attempt.topic}",
            recipients=[user.email],
        )
        msg.html = render_template(
            "results_email.html",
            user=user,
            attempt=attempt,
            weak_topics=weak_topics,
            recommended_next=recommended_next,
        )
        mail.send(msg)
    except Exception as e:
        # Log error but don't crash the app
        print(f"Failed to send email: {str(e)}")
        # Optionally: app.logger.error(f"Email error: {str(e)}")


# ---------------- ADMIN PANEL (Module 7) ----------------

def admin_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access only.", "danger")
            return redirect(url_for("dashboard"))
        return func(*args, **kwargs)

    return wrapper


@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    users = User.query.all()
    attempts = (
        QuizAttempt.query.order_by(QuizAttempt.started_at.desc())
        .limit(100)
        .all()
    )
    return render_template("admin.html", users=users, attempts=attempts)


@app.route("/admin/export_csv")
@login_required
@admin_required
def admin_export_csv():
    from io import StringIO
    import csv

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(
        ["user_email", "topic", "difficulty", "score", "total", "started_at"]
    )
    for a in QuizAttempt.query.order_by(QuizAttempt.started_at).all():
        writer.writerow(
            [
                a.user.email if a.user else "",
                a.topic,
                a.difficulty,
                a.score,
                a.total_questions,
                a.started_at.isoformat(),
            ]
        )
    output = si.getvalue()
    return (
        output,
        200,
        {
            "Content-Type": "text/csv",
            "Content-Disposition": "attachment; filename=quiz_attempts.csv",
        },
    )
#------------------------- Streak ----------------
from datetime import date, timedelta

def update_user_streak(user_id):
    """Update user's streak after completing a quiz"""
    streak = UserStreak.query.filter_by(user_id=user_id).first()
    today = date.today()
    
    if not streak:
        # First quiz ever
        streak = UserStreak(
            user_id=user_id,
            current_streak=1,
            longest_streak=1,
            last_quiz_date=today,
            total_quizzes=1
        )
        db.session.add(streak)
    else:
        streak.total_quizzes += 1
        
        if streak.last_quiz_date == today:
            # Already completed quiz today
            pass
        elif streak.last_quiz_date == today - timedelta(days=1):
            # Continuing streak
            streak.current_streak += 1
            streak.longest_streak = max(streak.longest_streak, streak.current_streak)
            streak.last_quiz_date = today
        else:
            # Streak broken
            days_missed = (today - streak.last_quiz_date).days
            if days_missed == 2 and not streak.freeze_used_this_week:
                # Can use freeze
                flash("🧊 Streak Freeze used! Your streak is safe.", "info")
                streak.freeze_used_this_week = True
                streak.current_streak += 1
                streak.last_quiz_date = today
            else:
                # Streak reset
                if streak.current_streak >= 3:
                    flash(f"💔 Streak broken! You had a {streak.current_streak}-day streak.", "warning")
                streak.current_streak = 1
                streak.last_quiz_date = today
    
    # Reset freeze on new week (Monday)
    if today.weekday() == 0:  # Monday
        streak.freeze_used_this_week = False
    
    db.session.commit()
    check_achievements(user_id)
    return streak


def update_weekly_goal(user_id):
    """Update user's weekly goal progress"""
    today = date.today()
    # Get Monday of current week
    week_start = today - timedelta(days=today.weekday())
    
    goal = WeeklyGoal.query.filter_by(
        user_id=user_id,
        week_start=week_start
    ).first()
    
    if not goal:
        goal = WeeklyGoal(
            user_id=user_id,
            week_start=week_start,
            goal_quizzes=10,
            completed_quizzes=1
        )
        db.session.add(goal)
    else:
        goal.completed_quizzes += 1
        if goal.completed_quizzes >= goal.goal_quizzes and not goal.is_completed:
            goal.is_completed = True
            flash(f"🎉 Weekly goal completed! You finished {goal.goal_quizzes} quizzes this week!", "success")
    
    db.session.commit()


def check_achievements(user_id):
    """Check and award new achievements"""
    streak = UserStreak.query.filter_by(user_id=user_id).first()
    if not streak:
        return
    
    # Check streak achievements
    streak_achievements = Achievement.query.filter_by(requirement_type='streak').all()
    for ach in streak_achievements:
        if streak.current_streak >= ach.requirement_value:
            # Check if already earned
            existing = UserAchievement.query.filter_by(
                user_id=user_id,
                achievement_id=ach.id
            ).first()
            if not existing:
                user_ach = UserAchievement(
                    user_id=user_id,
                    achievement_id=ach.id
                )
                db.session.add(user_ach)
                flash(f"🏆 Achievement Unlocked: {ach.name}!", "success")
    
    # Check total quizzes achievements
    total_achievements = Achievement.query.filter_by(requirement_type='total_quizzes').all()
    for ach in total_achievements:
        if streak.total_quizzes >= ach.requirement_value:
            existing = UserAchievement.query.filter_by(
                user_id=user_id,
                achievement_id=ach.id
            ).first()
            if not existing:
                user_ach = UserAchievement(
                    user_id=user_id,
                    achievement_id=ach.id
                )
                db.session.add(user_ach)
                flash(f"🏆 Achievement Unlocked: {ach.name}!", "success")
    
    db.session.commit()


# ---------------- CLI / ENTRYPOINT (Module 8) ----------------

@app.cli.command("init-db")
def init_db():
    with app.app_context():
        db.create_all()
        print("DB initialized")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        init_achievements()  # Add this line
    app.run(debug=True)

