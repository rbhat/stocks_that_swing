#!/usr/bin/env bash
# Provision the always-free e2-micro VM that runs the daily job + dashboard.
# Idempotent: every step checks first and skips loudly if already done.
# Does NOT run gcloud auth — if access is missing, it prints what to run
# and exits; the operator drives auth themselves.
#
# Usage: deploy/provision.sh
# Env overrides: STS_PROJECT STS_ZONE STS_INSTANCE
set -euo pipefail

PROJECT="${STS_PROJECT:-stocks-that-move}"
ZONE="${STS_ZONE:-us-west1-b}"
INSTANCE="${STS_INSTANCE:-sts-forward}"

echo "== provision.sh: project=${PROJECT} zone=${ZONE} instance=${INSTANCE} =="

if ! command -v gcloud >/dev/null 2>&1; then
    echo "ERROR: gcloud CLI not found on PATH." >&2
    exit 1
fi

echo "-- checking project access --"
if ! gcloud projects describe "${PROJECT}" >/dev/null 2>&1; then
    cat >&2 <<EOF
ERROR: cannot access project '${PROJECT}' with the active gcloud account.
Active account: $(gcloud config get-value account 2>/dev/null || echo '(none)')

Fix:
  gcloud auth login
  gcloud config set account <the-account-that-owns-${PROJECT}>
  gcloud config set project ${PROJECT}
Then re-run: deploy/provision.sh
EOF
    exit 1
fi
echo "   ok: project access confirmed"

echo "-- enabling compute.googleapis.com --"
if gcloud services list --project "${PROJECT}" --enabled \
        --filter="config.name:compute.googleapis.com" --format="value(config.name)" 2>/dev/null \
        | grep -q compute.googleapis.com; then
    echo "   already enabled"
else
    gcloud services enable compute.googleapis.com --project "${PROJECT}"
    echo "   enabled"
fi

echo "-- checking instance ${INSTANCE} --"
if gcloud compute instances describe "${INSTANCE}" \
        --project "${PROJECT}" --zone "${ZONE}" >/dev/null 2>&1; then
    echo "   already exists, skipping create"
else
    echo "   creating e2-micro (debian-12, 30GB pd-standard — always-free shape)"
    gcloud compute instances create "${INSTANCE}" \
        --project "${PROJECT}" \
        --zone "${ZONE}" \
        --machine-type e2-micro \
        --image-family debian-12 \
        --image-project debian-cloud \
        --boot-disk-size 30GB \
        --boot-disk-type pd-standard \
        --scopes cloud-platform
    echo "   created"
fi

# cloud-platform scope lets the VM's default service account authenticate to
# Artifact Registry (the default scope set cannot); the SA also needs the
# reader role. Both are idempotent and safe to re-run.
echo "-- granting Artifact Registry read to the VM's service account --"
COMPUTE_SA="$(gcloud compute instances describe "${INSTANCE}" \
    --project "${PROJECT}" --zone "${ZONE}" \
    --format 'value(serviceAccounts[0].email)')"
if gcloud projects get-iam-policy "${PROJECT}" \
        --flatten 'bindings[].members' \
        --filter "bindings.role=roles/artifactregistry.reader AND bindings.members=serviceAccount:${COMPUTE_SA}" \
        --format 'value(bindings.role)' 2>/dev/null | grep -q .; then
    echo "   already granted"
else
    gcloud projects add-iam-policy-binding "${PROJECT}" \
        --member "serviceAccount:${COMPUTE_SA}" \
        --role roles/artifactregistry.reader --condition=None >/dev/null
    echo "   granted to ${COMPUTE_SA}"
fi

echo "-- waiting for SSH --"
ssh_ready=0
for i in $(seq 1 20); do
    if gcloud compute ssh "${INSTANCE}" \
            --project "${PROJECT}" --zone "${ZONE}" \
            --tunnel-through-iap \
            --command "true" >/dev/null 2>&1; then
        ssh_ready=1
        break
    fi
    echo "   not ready yet (attempt ${i}/20), retrying in 10s..."
    sleep 10
done
if [ "${ssh_ready}" -ne 1 ]; then
    echo "ERROR: SSH did not become ready after 20 attempts. Re-run deploy/provision.sh in a bit." >&2
    exit 1
fi
echo "   ok: SSH reachable"

echo "-- checking docker on the VM --"
if gcloud compute ssh "${INSTANCE}" \
        --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
        --command "command -v docker" >/dev/null 2>&1; then
    echo "   docker already installed"
else
    echo "   installing docker + compose plugin (apt-get)"
    gcloud compute ssh "${INSTANCE}" \
        --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
        --command '
            set -e
            sudo apt-get update -qq
            sudo apt-get install -y -qq ca-certificates curl gnupg
            sudo install -m 0755 -d /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
            sudo chmod a+r /etc/apt/keyrings/docker.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
                | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
            sudo apt-get update -qq
            sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
            sudo usermod -aG docker "$(whoami)"
        '
    echo "   installed (docker group membership takes effect on next SSH login)"
fi

echo "-- setting VM timezone to America/Los_Angeles (cron lines are written in PT) --"
if gcloud compute ssh "${INSTANCE}" --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
        --command "timedatectl show -p Timezone --value" 2>/dev/null | grep -q "America/Los_Angeles"; then
    echo "   already set"
else
    gcloud compute ssh "${INSTANCE}" --project "${PROJECT}" --zone "${ZONE}" --tunnel-through-iap \
        --command "sudo timedatectl set-timezone America/Los_Angeles && sudo systemctl restart cron"
    echo "   set (cron restarted to pick up the new tz)"
fi

cat <<EOF

== provision.sh done ==
Instance '${INSTANCE}' in ${ZONE} (project ${PROJECT}) is up with Docker installed.
Next: deploy/deploy.sh
EOF
