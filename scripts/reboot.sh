#!/bin/bash

# Script to reboot a Debian server
# Logs execution to /var/log/reboot.log
# Requires sudo privileges without password

# Log execution
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Reboot initiated by $USER" >> /var/log/reboot.log

# Perform reboot
reboot

exit 0