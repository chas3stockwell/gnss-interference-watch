GNSS Interference Watch
Northwestern CS 310, Fall 2026

This file is the install note for the course artifact zip. The full guide,
architecture diagram, API, and teammate checklists are in README.md.

Requirements
- Python 3.12
- AWS SAM CLI and the AWS CLI, with course AWS credentials configured
- Docker, only when you switch the Reader Lambda to its container image

Run the tests
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements-dev.txt
    pytest
    ruff check .
    ruff format --check .

Run the map locally
    cd alert-show/web
    python3 -m http.server 8080
Then open http://localhost:8080 . The October slider uses illustrative
colors until you paste the deployed API URL into index.html
(window.GNSSIW_API_BASE).

Deploy the skeleton
    sam build -t infra/template.yaml
    sam deploy -t infra/template.yaml --guided
Leave StubMode at 1 until the TODO in a function is implemented. Set an AWS
budget alarm before the first backfill. Sample events for `sam local invoke`
are in events/.

There are no credentials and no data files in this tree. UCAR and GPSJam are
fetched at runtime by the Lambdas once those TODOs are filled in.
