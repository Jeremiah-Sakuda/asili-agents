#!/bin/bash
# Deploy Asili Agents to Google Cloud

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-asili-agents-hackathon}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="asili-agents"

echo "=== Asili Agents Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI is not installed"
    exit 1
fi

# Check if logged in
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n 1 > /dev/null 2>&1; then
    echo "Error: Not logged in to gcloud. Run 'gcloud auth login'"
    exit 1
fi

# Set project
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    run.googleapis.com \
    aiplatform.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com

# Create Artifact Registry repository if it doesn't exist
echo "Setting up Artifact Registry..."
gcloud artifacts repositories create "$SERVICE_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Asili Agents container images" \
    2>/dev/null || echo "Repository already exists"

# Configure Docker auth
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

# Build and push image
IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$SERVICE_NAME/$SERVICE_NAME:latest"
echo "Building image: $IMAGE_TAG"

docker build -t "$IMAGE_TAG" .
docker push "$IMAGE_TAG"

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --image "$IMAGE_TAG" \
    --platform managed \
    --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID" \
    --set-env-vars "GOOGLE_CLOUD_LOCATION=$REGION" \
    --set-env-vars "DEMO_MODE=true" \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 10

# Get the URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format 'value(status.url)')

echo ""
echo "=== Deployment Complete ==="
echo "Service URL: $SERVICE_URL"
echo ""
echo "Test with:"
echo "  curl $SERVICE_URL"
echo "  curl $SERVICE_URL/api/seller"
