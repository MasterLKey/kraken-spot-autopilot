terraform {
  required_version = ">= 1.6"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.76"
    }
  }
}

provider "proxmox" {
  endpoint  = "https://${var.proxmox_host}:8006/"
  api_token = var.proxmox_api_token
  insecure  = true
}

# Template already present on the node (shared with other LXCs).
locals {
  ubuntu_template = "local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
}

resource "proxmox_virtual_environment_container" "crypto_bot" {
  node_name   = var.proxmox_node
  vm_id       = var.container_id
  description = "Kraken Spot Autopilot — personal DCA/grid bot"
  tags        = ["crypto-bot", "docker"]

  start_on_boot = true
  started       = true
  unprivileged  = true

  operating_system {
    template_file_id = local.ubuntu_template
    type             = "ubuntu"
  }

  cpu {
    cores = 1
  }

  memory {
    dedicated = 1024
  }

  disk {
    datastore_id = var.storage
    size         = 16
  }

  network_interface {
    name   = "eth0"
    bridge = "vmbr0"
  }

  features {
    nesting = true
  }

  initialization {
    hostname = "crypto-bot"

    user_account {
      keys     = [var.ssh_public_key]
      password = var.root_password
    }

    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }
  }
}
