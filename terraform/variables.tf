variable "proxmox_host" {
  description = "IP address or hostname of your Proxmox server"
  type        = string
  default     = "192.168.4.223"
}

variable "proxmox_node" {
  description = "Proxmox node name"
  type        = string
  default     = "pm01"
}

variable "proxmox_api_token" {
  description = "Proxmox API token in the form USER@REALM!TOKENID=SECRET"
  type        = string
  sensitive   = true
}

variable "storage" {
  description = "Proxmox storage pool for the container disk"
  type        = string
  default     = "local-lvm"
}

variable "container_id" {
  description = "Proxmox container ID (VMID)"
  type        = number
  default     = 202
}

variable "ssh_public_key" {
  description = "SSH public key for root access"
  type        = string
}

variable "root_password" {
  description = "Root password for Proxmox console access"
  type        = string
  sensitive   = true
}
