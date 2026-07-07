from fastapi import FastAPI

app = FastAPI(title="BPO Unified Optimization Engine")


@app.get("/")
def root():
    return {"status": "running"}