from pathlib import Path

from flask import Flask, send_file


ROOT = Path(__file__).resolve().parent
app = Flask(__name__)


@app.get("/")
def home():
    return send_file(ROOT / "index.html")


@app.get("/guide")
@app.get("/guide/")
@app.get("/guide.html")
def guide():
    return send_file(ROOT / "guide.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
