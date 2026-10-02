import os

# Set dummy environment variables to bypass lifespan fail-fast checks in tests
os.environ["POSTGRES_URL"] = "postgresql://postgres:postgres@localhost:5432/dummy"
os.environ["INTERNAL_SERVICE_SECRET"] = "dummy-secret"
