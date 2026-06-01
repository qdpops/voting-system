import os
import sqlite3
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from auth import generate_token
from database import init_db, get_db
from email_utils import send_voting_link

app = FastAPI()
templates = Jinja2Templates(directory="templates")
init_db()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "supersecret123")


def verify_admin(token: str):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Неверный токен администратора")


# ── Admin panel ───────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, token: str = ""):
    if not token or token != ADMIN_TOKEN:
        return templates.TemplateResponse(
            request, "admin_login.html",
            {"error": "Неверный токен" if token else None},
            status_code=403 if token else 200,
        )
    now = datetime.now().isoformat()
    with get_db() as conn:
        users = [dict(r) for r in conn.execute(
            "SELECT id, org_name, oto_number, email FROM users ORDER BY id DESC"
        ).fetchall()]
        votings_raw = conn.execute(
            "SELECT id, question, ends_at, launched FROM votings ORDER BY id DESC"
        ).fetchall()
        votings = [
            {
                **dict(v),
                "is_draft":  not bool(v["launched"]),
                "is_active": bool(v["launched"]) and v["ends_at"] > now,
                "is_ended":  bool(v["launched"]) and v["ends_at"] <= now,
            }
            for v in votings_raw
        ]
    return templates.TemplateResponse(request, "admin.html", {
        "users": users,
        "votings": votings,
        "admin_token": token,
    })


# ── Participants ──────────────────────────────────────────────────────────────

@app.post("/admin/add_user")
def add_user(
    org_name: str = Form(...),
    oto_number: str = Form(...),
    email: str = Form(...),
    admin_token: str = Form(...),
):
    verify_admin(admin_token)
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO users (org_name, oto_number, email) VALUES (?, ?, ?)",
                (org_name, oto_number, email),
            )
            conn.commit()
            return {"status": "ok", "message": f"Участник {email} добавлен"}
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Email уже зарегистрирован")


@app.post("/admin/delete_user")
def delete_user(user_id: int = Form(...), admin_token: str = Form(...)):
    verify_admin(admin_token)
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return {"status": "ok"}


# ── Votings ───────────────────────────────────────────────────────────────────

@app.post("/admin/create_voting")
def create_voting(
    question: str = Form(...),
    hours_valid: int = Form(...),
    admin_token: str = Form(...),
):
    """Создаёт черновик голосования без рассылки."""
    verify_admin(admin_token)
    ends_at = datetime.now() + timedelta(hours=hours_valid)
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO votings (question, ends_at, launched) VALUES (?, ?, 0)",
            (question, ends_at.isoformat()),
        )
        voting_id = cursor.lastrowid
        conn.commit()
    return {"status": "ok", "voting_id": voting_id}


@app.post("/admin/launch_voting")
def launch_voting(
    voting_id: int = Form(...),
    admin_token: str = Form(...),
    request: Request = None,
):
    """Запускает голосование: рассылает ссылки и блокирует редактирование."""
    verify_admin(admin_token)
    with get_db() as conn:
        voting = conn.execute(
            "SELECT id, question, ends_at, launched FROM votings WHERE id = ?",
            (voting_id,),
        ).fetchone()
        if not voting:
            raise HTTPException(404, "Голосование не найдено")
        if voting["launched"]:
            raise HTTPException(400, "Голосование уже запущено")

        users = conn.execute("SELECT id, email FROM users").fetchall()
        if not users:
            raise HTTPException(400, "Нет участников для рассылки")

        base_url = str(request.base_url).rstrip("/")
        sent, errors = 0, []

        for user in users:
            token = generate_token()
            try:
                conn.execute(
                    "INSERT INTO voting_tokens (voting_id, user_id, token) VALUES (?, ?, ?)",
                    (voting_id, user["id"], token),
                )
                send_voting_link(user["email"], voting_id, token, base_url)
                sent += 1
            except Exception as exc:
                errors.append(f"{user['email']}: {exc}")

        conn.execute("UPDATE votings SET launched = 1 WHERE id = ?", (voting_id,))
        conn.commit()

    result = {"status": "ok", "voting_id": voting_id, "sent": sent}
    if errors:
        result["errors"] = errors
    return result


@app.post("/admin/edit_voting")
def edit_voting(
    voting_id: int = Form(...),
    question: str = Form(...),
    ends_at: str = Form(...),
    admin_token: str = Form(...),
):
    verify_admin(admin_token)
    with get_db() as conn:
        voting = conn.execute(
            "SELECT launched FROM votings WHERE id = ?", (voting_id,)
        ).fetchone()
        if not voting:
            raise HTTPException(404, "Голосование не найдено")
        if voting["launched"]:
            raise HTTPException(400, "Запущенное голосование нельзя редактировать")
        conn.execute(
            "UPDATE votings SET question = ?, ends_at = ? WHERE id = ?",
            (question, ends_at, voting_id),
        )
        conn.commit()
    return {"status": "ok"}


@app.post("/admin/delete_voting")
def delete_voting(voting_id: int = Form(...), admin_token: str = Form(...)):
    """Удаляет голосование вместе со всеми голосами и токенами."""
    verify_admin(admin_token)
    with get_db() as conn:
        conn.execute("DELETE FROM votes WHERE voting_id = ?", (voting_id,))
        conn.execute("DELETE FROM voting_tokens WHERE voting_id = ?", (voting_id,))
        conn.execute("DELETE FROM votings WHERE id = ?", (voting_id,))
        max_id = conn.execute("SELECT MAX(id) FROM votings").fetchone()[0]
        if max_id is None:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'votings'")
        else:
            conn.execute(
                "UPDATE sqlite_sequence SET seq = ? WHERE name = 'votings'", (max_id,)
            )
        conn.commit()
    return {"status": "ok"}


# ── Vote page ─────────────────────────────────────────────────────────────────

@app.get("/vote/{voting_id}/{token}", response_class=HTMLResponse)
def vote_page(request: Request, voting_id: int, token: str):
    with get_db() as conn:
        inv = conn.execute(
            """SELECT vt.id, vt.used, u.org_name
               FROM voting_tokens vt
               JOIN users u ON u.id = vt.user_id
               WHERE vt.voting_id = ? AND vt.token = ?""",
            (voting_id, token),
        ).fetchone()

        if not inv:
            return templates.TemplateResponse(request, "vote.html", {
                "error": "Ссылка недействительна", "error_type": "invalid",
            }, status_code=404)

        voting = conn.execute(
            "SELECT id, question, ends_at, launched FROM votings WHERE id = ?",
            (voting_id,),
        ).fetchone()

        if not voting:
            return templates.TemplateResponse(request, "vote.html", {
                "error": "Голосование не найдено", "error_type": "invalid",
            }, status_code=404)

        if inv["used"]:
            return templates.TemplateResponse(request, "vote.html", {
                "error": "Вы уже проголосовали", "error_type": "already_voted",
            })

        now = datetime.now()
        ends_at = datetime.fromisoformat(voting["ends_at"])
        if now > ends_at:
            return templates.TemplateResponse(request, "vote.html", {
                "error": "Голосование завершено", "error_type": "expired",
            })

        time_left = ends_at - now
        h = int(time_left.total_seconds() // 3600)
        m = int((time_left.total_seconds() % 3600) // 60)
        if time_left.total_seconds() < 60:
            time_left_str = "менее 1 мин"
        elif h == 0:
            time_left_str = f"{m} мин"
        else:
            time_left_str = f"{h}ч {m}мин" if m else f"{h}ч"

    return templates.TemplateResponse(request, "vote.html", {
        "question": voting["question"],
        "voting_id": voting_id,
        "token": token,
        "org_name": inv["org_name"],
        "time_left_str": time_left_str,
    })


@app.post("/vote/{voting_id}/{token}")
def submit_vote(voting_id: int, token: str, choice: str = Form(...)):
    if choice not in ("for", "against", "abstained"):
        raise HTTPException(400, "Некорректный выбор")

    with get_db() as conn:
        inv = conn.execute(
            "SELECT id, user_id, used FROM voting_tokens WHERE voting_id = ? AND token = ?",
            (voting_id, token),
        ).fetchone()
        if not inv:
            raise HTTPException(404, "Ссылка недействительна")
        if inv["used"]:
            raise HTTPException(400, "Вы уже проголосовали")

        voting = conn.execute(
            "SELECT ends_at, launched FROM votings WHERE id = ?", (voting_id,)
        ).fetchone()
        if not voting or not voting["launched"]:
            raise HTTPException(400, "Голосование недоступно")
        if datetime.now() > datetime.fromisoformat(voting["ends_at"]):
            raise HTTPException(400, "Время голосования истекло")

        try:
            conn.execute(
                "INSERT INTO votes (voting_id, user_id, choice) VALUES (?, ?, ?)",
                (voting_id, inv["user_id"], choice),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Голос уже учтён")

        conn.execute("UPDATE voting_tokens SET used = 1 WHERE id = ?", (inv["id"],))
        conn.commit()

    return {"status": "ok", "message": "Голос принят"}


# ── Results ───────────────────────────────────────────────────────────────────

@app.get("/results/{voting_id}", response_class=HTMLResponse)
def results_page(request: Request, voting_id: int, admin_token: str):
    verify_admin(admin_token)
    with get_db() as conn:
        voting = conn.execute(
            "SELECT id, question, ends_at, created_at FROM votings WHERE id = ?",
            (voting_id,),
        ).fetchone()
        if not voting:
            raise HTTPException(404, "Голосование не найдено")
        stats = conn.execute(
            "SELECT choice, COUNT(*) AS cnt FROM votes WHERE voting_id = ? GROUP BY choice",
            (voting_id,),
        ).fetchall()
        total_invited = conn.execute(
            "SELECT COUNT(*) FROM voting_tokens WHERE voting_id = ?", (voting_id,)
        ).fetchone()[0]

    res = {"for": 0, "against": 0, "abstained": 0}
    for row in stats:
        res[row["choice"]] = row["cnt"]
    total_voted = sum(res.values())
    quorum = round(total_voted / total_invited * 100, 1) if total_invited else 0

    return templates.TemplateResponse(request, "results.html", {
        "voting": dict(voting),
        "votes_for": res["for"],
        "votes_against": res["against"],
        "votes_abstained": res["abstained"],
        "total_voted": total_voted,
        "total_invited": total_invited,
        "quorum": quorum,
        "admin_token": admin_token,
    })


@app.get("/results/{voting_id}/json")
def results_json(voting_id: int, admin_token: str):
    verify_admin(admin_token)
    with get_db() as conn:
        voting = conn.execute(
            "SELECT ends_at FROM votings WHERE id = ?", (voting_id,)
        ).fetchone()
        if not voting:
            raise HTTPException(404, "Голосование не найдено")
        stats = conn.execute(
            "SELECT choice, COUNT(*) AS cnt FROM votes WHERE voting_id = ? GROUP BY choice",
            (voting_id,),
        ).fetchall()
        total_invited = conn.execute(
            "SELECT COUNT(*) FROM voting_tokens WHERE voting_id = ?", (voting_id,)
        ).fetchone()[0]

    res = {"for": 0, "against": 0, "abstained": 0}
    for row in stats:
        res[row["choice"]] = row["cnt"]
    total_voted = sum(res.values())
    return {"total_invited": total_invited, "total_votes": total_voted, **res}
