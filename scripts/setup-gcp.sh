#!/bin/bash
# Set up a new Google Cloud project for Asili Agents
# Run this once to create the project and enable services

set -e

# Configuration
PROJECT_ID="${1:-asili-agents-hackathon}"
BILLING_ACCOUNT="${BILLING_ACCOUNT:-}"
REGION="us-central1"

echo "=== Asili Agents GCP Setup ==="
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI is not installed"
    echo "Install from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if logged in
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n 1 > /dev/null 2>&1; then
    echo "Not logged in. Running 'gcloud auth login'..."
    gcloud auth login
fi

# Create project
echo "Creating project $PROJECT_ID..."
gcloud projects create "$PROJECT_ID" --name="Asili Agents Hackathon" 2>/dev/null || echo "Project may already exist"

# Set as current project
gcloud config set project "$PROJECT_ID"

# Link billing (if provided)
if [ -n "$BILLING_ACCOUNT" ]; then
    echo "Linking billing account..."
    gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
else
    echo ""
    echo "WARNING: No billing account linked."
    echo "To link billing, run:"
    echo "  gcloud billing projects link $PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT"
    echo ""
    echo "Or set BILLING_ACCOUNT environment variable and re-run this script."
    echo ""
fi

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    run.googleapis.com \
    aiplatform.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    discoveryengine.googleapis.com

# Create service account for CI/CD
SA_NAME="github-actions"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

echo "Creating service account for CI/CD..."
gcloud iam service-accounts create "$SA_NAME" \
    --display-name="GitHub Actions" \
    --description="Service account for CI/CD deployments" \
    2>/dev/null || echo "Service account may already exist"

# Grant permissions
echo "Granting permissions..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/run.admin" \
    --quiet

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/artifactregistry.writer" \
    --quiet

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/iam.serviceAccountUser" \
    --quiet

# Create Artifact Registry repository
echo "Creating Artifact Registry repository..."
gcloud artifacts repositories create asili-agents \
    --repository-format=docker \
    --location="$REGION" \
    --description="Asili Agents container images" \
    2>/dev/null || echo "Repository may already exist"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Project: $PROJECT_ID"
echo "Service Account: $SA_EMAIL"
echo ""
echo "Next steps:"
echo "1. Link a billing account if not already done"
echo "2. Set up Workload Identity Federation for GitHub Actions"
echo "3. Add the following secrets to your GitHub repository:"
echo "   - GCP_PROJECT_ID: $PROJECT_ID"
echo "   - WIF_PROVIDER: (from Workload Identity setup)"
echo "   - WIF_SERVICE_ACCOUNT: $SA_EMAIL"
echo ""
echo "To deploy manually, run:"
echo "  ./scripts/deploy.sh"
