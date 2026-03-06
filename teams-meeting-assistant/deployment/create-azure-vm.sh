#!/bin/bash
# Creates the Azure Windows VM for Teams Meeting Assistant.
# Run from your local machine with Azure CLI installed (az login first).
#
# Usage:
#   chmod +x create-azure-vm.sh
#   ./create-azure-vm.sh

set -euo pipefail

RESOURCE_GROUP="yoda-media-bot-rg"
VM_NAME="yoda-media-bot-vm"
LOCATION="centralindia"
VM_SIZE="Standard_D2s_v3"
ADMIN_USER="azureadmin"
IMAGE="MicrosoftWindowsServer:WindowsServer:2022-Datacenter:latest"

echo "=== Creating Azure VM for Teams Meeting Assistant ==="
echo "Resource Group: $RESOURCE_GROUP"
echo "VM Name:        $VM_NAME"
echo "Location:       $LOCATION"
echo "Size:           $VM_SIZE"
echo ""

# Prompt for admin password
read -sp "Enter admin password for VM (min 12 chars, needs uppercase+lowercase+number+special): " ADMIN_PASSWORD
echo ""

# Step 1: Create resource group
echo "[1/5] Creating resource group..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

# Step 2: Create the VM with public IP + DNS label
DNS_LABEL="yoda-media-bot"
echo "[2/5] Creating Windows VM (this takes 3-5 minutes)..."
az vm create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --size "$VM_SIZE" \
  --image "$IMAGE" \
  --public-ip-sku Standard \
  --public-ip-address-dns-name "$DNS_LABEL" \
  --admin-username "$ADMIN_USER" \
  --admin-password "$ADMIN_PASSWORD" \
  --nsg-rule RDP \
  --output table

# Step 3: Open required ports
echo "[3/5] Opening ports..."

# HTTPS for web traffic
az vm open-port --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --port 443 --priority 1010 --output none
echo "  Port 443 (HTTPS) opened"

# HTTP for Let's Encrypt validation
az vm open-port --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --port 80 --priority 1015 --output none
echo "  Port 80 (HTTP) opened"

# TCP 8445-9000 for media signaling
az vm open-port --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --port 8445-9000 --priority 1020 --output none
echo "  Ports 8445-9000 (TCP) opened"

# UDP 8445-9000 for SRTP media
az network nsg rule create \
  --resource-group "$RESOURCE_GROUP" \
  --nsg-name "${VM_NAME}NSG" \
  --name "AllowMediaUDP" \
  --priority 1030 \
  --protocol Udp \
  --destination-port-ranges 8445-9000 \
  --access Allow \
  --direction Inbound \
  --output none
echo "  Ports 8445-9000 (UDP) opened"

# Step 4: Get VM details
echo "[4/5] Getting VM details..."
PUBLIC_IP=$(az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --show-details --query publicIps -o tsv)
FQDN="${DNS_LABEL}.${LOCATION}.cloudapp.azure.com"

# Step 5: Print summary
echo ""
echo "[5/5] Done!"
echo ""
echo "============================================"
echo "  Azure VM Created Successfully"
echo "============================================"
echo ""
echo "  Public IP: $PUBLIC_IP"
echo "  FQDN:      $FQDN"
echo "  RDP:       mstsc /v:$PUBLIC_IP"
echo "  Username:  $ADMIN_USER"
echo ""
echo "NEXT STEPS:"
echo "  1. RDP into the VM:  mstsc /v:$PUBLIC_IP"
echo "  2. Copy project files to C:\\yoda on the VM"
echo "  3. Run deploy-vm.ps1 as Administrator:"
echo "       .\\deploy-vm.ps1 -Domain \"$FQDN\" -PublicIp \"$PUBLIC_IP\""
echo "  4. Update Azure Bot messaging endpoint to:"
echo "       https://$FQDN/api/callbacks"
echo ""
echo "To deallocate (save costs when not testing):"
echo "  az vm deallocate -g $RESOURCE_GROUP -n $VM_NAME"
echo ""
echo "To start again:"
echo "  az vm start -g $RESOURCE_GROUP -n $VM_NAME"
echo ""
