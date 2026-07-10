from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "Unstop Hackathon Bot is running!", 200

@app.route("/health")
def health():
    return "ok", 200