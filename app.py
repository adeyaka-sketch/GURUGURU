import os

from dotenv import load_dotenv
from flask import Flask, send_from_directory

load_dotenv()

from drop.db import init_db  # noqa: E402
from drop.routes.analytics import bp as analytics_bp  # noqa: E402
from drop.routes.billing import bp as billing_bp  # noqa: E402
from drop.routes.dialogue import bp as dialogue_bp  # noqa: E402
from drop.routes.individuality_c import bp as individuality_c_bp  # noqa: E402
from drop.routes.personalities import bp as personalities_bp  # noqa: E402
from drop.routes.relationships import bp as relationships_bp  # noqa: E402
from drop.routes.scenes import bp as scenes_bp  # noqa: E402
from drop.routes.self_discovery import bp as self_discovery_bp  # noqa: E402

PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "public")

app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    print("[警告] SECRET_KEY が未設定です。開発用の固定キーを使用します(本番では.envに設定してください)。")
    _secret_key = "dev-insecure-secret-change-me"
app.secret_key = _secret_key

init_db()

app.register_blueprint(personalities_bp)
app.register_blueprint(dialogue_bp)
app.register_blueprint(individuality_c_bp)
app.register_blueprint(relationships_bp)
app.register_blueprint(self_discovery_bp)
app.register_blueprint(scenes_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(analytics_bp)


@app.get("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[警告] ANTHROPIC_API_KEY が未設定です。.env を作成してください(.env.example参照)。")
    port = int(os.environ.get("PORT", 3000))
    print(f"DROP app running at http://localhost:{port}")
    app.run(port=port, debug=False)
