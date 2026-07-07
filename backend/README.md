# create virtual environment

py -m venv venv

# activate virtual environment

.\venv\Scripts\Activate.ps1

# install packages from requirements.txt file

pip install -r requirements.txt

# Start backend server

uvicorn app.main:app --reload --port 8000
