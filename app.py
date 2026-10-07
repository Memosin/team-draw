import io
import csv
import json
import os
import random
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from flask import Flask, abort, current_app, g, redirect, render_template, request, send_file, url_for
from dotenv import load_dotenv
import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

_PDF_FONT_DIR = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
if "TeamDrawSans" not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont("TeamDrawSans", os.path.join(_PDF_FONT_DIR, "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("TeamDrawSans-Bold", os.path.join(_PDF_FONT_DIR, "VeraBd.ttf")))
    pdfmetrics.registerFontFamily(
        "TeamDrawSans",
        normal="TeamDrawSans",
        bold="TeamDrawSans-Bold",
        italic="TeamDrawSans",
        boldItalic="TeamDrawSans-Bold",
    )


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        APP_NAME=os.getenv("APP_NAME", "Team Draw"),
        CAPTAIN_LABEL=os.getenv("CAPTAIN_LABEL", "Captains"),
        PARTICIPANT_LABEL=os.getenv("PARTICIPANT_LABEL", "Fishermen"),
        TEAM_LABEL=os.getenv("TEAM_LABEL", "Team"),
        DATABASE=os.getenv("DATABASE_PATH", os.path.join(app.instance_path, "team_draw.sqlite3")),
    )
    if test_config:
        app.config.update(test_config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    database_path = app.config["DATABASE"]
    if database_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(database_path)), exist_ok=True)
    _initialize_database(database_path)

    @app.teardown_appcontext
    def close_db(_error=None):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.get("/")
    def index():
        return render_template("index.html", settings=_settings())

    @app.post("/draw")
    def create_draw():
        title = request.form.get("title", "").strip() or "Team draw"
        captains = _parse_names(request.form.get("captains", ""))
        participants = _parse_names(request.form.get("participants", ""))
        errors = []

        if len(title) > 100:
            errors.append("Draw name must be 100 characters or fewer.")
        if not captains:
            errors.append(f"Add at least one {current_app.config['CAPTAIN_LABEL'].lower()}.")
        elif len(captains) > 50:
            errors.append("A draw can have at most 50 captains.")
        if len(participants) > 500:
            errors.append("A draw can have at most 500 participants.")
        if any(len(name) > 100 for name in captains + participants):
            errors.append("Names must be 100 characters or fewer.")

        try:
            max_team_size = int(request.form.get("max_team_size", ""))
            if not 2 <= max_team_size <= 50:
                raise ValueError
        except (TypeError, ValueError):
            max_team_size = 0
            errors.append("Maximum team size must be between 2 and 50, including the captain.")

        if errors:
            return render_template(
                "index.html",
                settings=_settings(),
                values=request.form,
                errors=errors,
            ), 400

        shuffled = participants[:]
        random.SystemRandom().shuffle(shuffled)
        assignable_count = min(len(shuffled), len(captains) * (max_team_size - 1))
        assignable = shuffled[:assignable_count]
        overflow = shuffled[assignable_count:]
        teams = [
            {
                "name": f"{current_app.config['TEAM_LABEL']} {number}",
                "captain": captain,
                "participants": [],
            }
            for number, captain in enumerate(captains, start=1)
        ]
        for index, participant in enumerate(assignable):
            teams[index % len(teams)]["participants"].append(participant)

        created_at = datetime.now(timezone.utc).isoformat(timespec="minutes")
        draw = {
            "title": title,
            "captain_label": current_app.config["CAPTAIN_LABEL"],
            "participant_label": current_app.config["PARTICIPANT_LABEL"],
            "teams": teams,
            "overflow": overflow,
            "max_team_size": max_team_size,
            "participant_count": len(participants),
            "created_at": created_at,
        }
        token = secrets.token_urlsafe(24)
        connection = _get_db()
        connection.execute(
            "INSERT INTO saved_draw (token, payload, created_at) VALUES (?, ?, ?)",
            (token, json.dumps(draw, ensure_ascii=False), created_at),
        )
        connection.commit()
        return redirect(url_for("view_draw", token=token), code=303)

    @app.get("/draw/<token>")
    def view_draw(token):
        draw = _load_draw(token)
        response = current_app.make_response(
            render_template("draw.html", draw=draw, share_url=url_for("view_draw", token=token, _external=True))
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.get("/draw/<token>/pdf")
    def download_pdf(token):
        draw = _load_draw(token)
        output = io.BytesIO()
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "DrawTitle", parent=styles["Title"], fontName="TeamDrawSans-Bold", fontSize=24,
            leading=29, alignment=TA_LEFT, textColor=colors.HexColor("#173335"), spaceAfter=8,
        )
        heading_style = ParagraphStyle(
            "TeamHeading", parent=styles["Heading2"], fontName="TeamDrawSans-Bold", fontSize=14,
            leading=18, textColor=colors.HexColor("#173335"), spaceBefore=10, spaceAfter=4,
        )
        body_style = ParagraphStyle(
            "DrawBody", parent=styles["BodyText"], fontName="TeamDrawSans", fontSize=10,
            leading=15, textColor=colors.HexColor("#34494a"),
        )
        overflow_style = ParagraphStyle(
            "OverflowHeading", parent=heading_style, textColor=colors.HexColor("#bd472e"),
        )
        document = SimpleDocTemplate(
            output, pagesize=letter, rightMargin=0.7 * inch, leftMargin=0.7 * inch,
            topMargin=0.65 * inch, bottomMargin=0.65 * inch,
            title=draw["title"], author=current_app.config["APP_NAME"],
        )
        story = [
            Paragraph(escape(draw["title"]), title_style),
            Paragraph(f"Saved {escape(draw['created_at'])} &bull; {len(draw['teams'])} teams", body_style),
            Spacer(1, 14),
        ]
        for number, team in enumerate(draw["teams"], start=1):
            team_lines = [
                Paragraph(f"{number}. {escape(team['name'])}", heading_style),
                Paragraph(f"{escape(draw['captain_label'])}: <b>{escape(team['captain'])}</b>", body_style),
            ]
            team_lines.extend(Paragraph(f"&bull; {escape(name)}", body_style) for name in team["participants"])
            story.append(KeepTogether(team_lines))
            story.append(Spacer(1, 5))
        if draw["overflow"]:
            story.append(Paragraph(f"Overflow ({len(draw['overflow'])})", overflow_style))
            story.extend(Paragraph(f"&bull; {escape(name)}", body_style) for name in draw["overflow"])
        document.build(story)
        output.seek(0)
        slug = re.sub(r"[^a-z0-9]+", "-", draw["title"].lower()).strip("-") or "team-draw"
        response = send_file(output, mimetype="application/pdf", as_attachment=True, download_name=f"{slug}.pdf")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    return app


def _settings():
    return {
        "app_name": current_app.config["APP_NAME"],
        "captain_label": current_app.config["CAPTAIN_LABEL"],
        "participant_label": current_app.config["PARTICIPANT_LABEL"],
    }


def _parse_names(value):
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) == 1 and "," in lines[0]:
        try:
            names = next(csv.reader([lines[0]], skipinitialspace=True))
        except csv.Error:
            return lines
        return [name.strip() for name in names if name.strip()]
    return lines


def _initialize_database(database_path):
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS saved_draw ("
            "id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, "
            "payload TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.commit()
    finally:
        connection.close()


def _get_db():
    if "db" not in g:
        connection = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        connection.row_factory = sqlite3.Row
        g.db = connection
    return g.db


def _load_draw(token):
    row = _get_db().execute("SELECT payload FROM saved_draw WHERE token = ?", (token,)).fetchone()
    if row is None:
        abort(404)
    return json.loads(row["payload"])


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_DEBUG") == "1")