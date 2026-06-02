#!/usr/bin/env bash
# Provision the SignSpeak GPU VM on Google Cloud.
#
# Prereqs (do these FIRST in the Cloud Console):
#   1. Upgrade the free-trial account to a paid account (still draws on the
#      $300 credit; no charge until it is exhausted) — GPUs are blocked otherwise.
#   2. Request GPU quota: IAM & Admin -> Quotas -> filter "NVIDIA L4 GPUs" in
#      us-central1 -> request 1. Approval can take minutes to hours.
#
# Run locally with gcloud authenticated:  bash 01-create-vm.sh
set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project)}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
INSTANCE="${INSTANCE:-signspeak}"
MACHINE="${MACHINE:-g2-standard-8}"   # 8 vCPU, 32 GB RAM, 1x L4 (24 GB)
DISK_GB="${DISK_GB:-80}"

echo ">> Reserving static IP (idempotent)..."
gcloud compute addresses create signspeak-ip --region="$REGION" 2>/dev/null || true
STATIC_IP="$(gcloud compute addresses describe signspeak-ip --region="$REGION" --format='value(address)')"
echo "   Static IP: $STATIC_IP"

echo ">> Creating instance $INSTANCE ($MACHINE, 1x NVIDIA L4)..."
gcloud compute instances create "$INSTANCE" \
  --project="$PROJECT" --zone="$ZONE" \
  --machine-type="$MACHINE" \
  --accelerator=type=nvidia-l4,count=1 \
  --maintenance-policy=TERMINATE \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size="${DISK_GB}GB" --boot-disk-type=pd-balanced \
  --address=signspeak-ip \
  --tags=http-server,https-server

echo ">> Opening firewall for HTTP/HTTPS (idempotent)..."
gcloud compute firewall-rules create allow-http  --allow=tcp:80  --target-tags=http-server  2>/dev/null || true
gcloud compute firewall-rules create allow-https --allow=tcp:443 --target-tags=https-server 2>/dev/null || true

echo ""
echo "Done. Your DOMAIN (sslip.io, free, no domain purchase needed):"
echo "    DOMAIN=${STATIC_IP}.sslip.io"
echo "Next: ssh in and run 02-setup-vm.sh"
echo "    gcloud compute ssh ${INSTANCE} --zone=${ZONE}"
