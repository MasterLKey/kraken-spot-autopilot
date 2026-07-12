output "container_id" {
  description = "Proxmox VMID of the created container"
  value       = proxmox_virtual_environment_container.crypto_bot.vm_id
}

output "next_steps" {
  description = "What to do after terraform apply"
  value       = <<-EOT

    Container ${proxmox_virtual_environment_container.crypto_bot.vm_id} created on ${var.proxmox_node}.

    Next:
    1. Find IP in Proxmox UI (CT ${proxmox_virtual_environment_container.crypto_bot.vm_id} → Summary)
    2. scp -i ~/.ssh/octo_scrape_deploy scripts/provision.sh root@<IP>:/root/provision.sh
    3. ssh ... "bash /root/provision.sh"
    4. scp .env to /opt/kraken-spot-autopilot/.env (mode 600)
    5. ssh ... "bash /opt/kraken-spot-autopilot/start.sh"
  EOT
}
