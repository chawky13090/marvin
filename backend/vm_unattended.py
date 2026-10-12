"""Unattended VM installation material with host-protected credentials.

Debian uses a passwordless Ed25519 key.  Windows Setup necessarily needs the
temporary local password in Autounattend.xml; callers must ACL the work folder
and destroy both the XML and its seed ISO after Setup completes.
"""
from __future__ import annotations

import html
import json
import os
import secrets
import string
import time
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import dpapi_secret_store


DEBIAN_KEY_SECRET: Final[str] = "vm_lab.debian13.ssh_private_key"
WINDOWS_PASSWORD_SECRET: Final[str] = "vm_lab.windows11.guest_password"
WINDOWS_ADMIN_PASSWORD_SECRET: Final[str] = "vm_lab.windows11.admin_password"
WINDOWS_USERNAME: Final[str] = "marvin"
WINDOWS_ADMIN_USERNAME: Final[str] = "marvin-lab-admin"
DEBIAN_USERNAME: Final[str] = "marvin"


class VMUnattendedError(RuntimeError):
    pass


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _metadata(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _new_password(length: int = 32) -> str:
    if length < 24:
        raise VMUnattendedError("Un secret de VM doit contenir au moins 24 caractères.")
    alphabet = string.ascii_letters + string.digits + "-_.!@#%"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in value) and any(c.isupper() for c in value)
                and any(c.isdigit() for c in value) and any(c in "-_.!@#%" for c in value)):
            return value


def prepare_debian(work_directory: Path) -> dict[str, Any]:
    """Create public preseed material and keep the private SSH key in DPAPI."""
    private = Ed25519PrivateKey.generate()
    private_text = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_text = private.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    dpapi_secret_store.set_secret(DEBIAN_KEY_SECRET, private_text)

    preseed = f"""# Marvin Debian 13 Test Forge - generated, contains no private credential
d-i debian-installer/locale string en_GB.UTF-8
d-i keyboard-configuration/xkb-keymap select fr
d-i netcfg/choose_interface select auto
d-i netcfg/get_hostname string marvin-debian-testforge
d-i netcfg/get_domain string local
d-i mirror/country string manual
d-i mirror/http/hostname string deb.debian.org
d-i mirror/http/directory string /debian
d-i mirror/http/proxy string
d-i clock-setup/utc boolean true
d-i time/zone string Europe/Paris
d-i clock-setup/ntp boolean true
d-i passwd/root-login boolean false
d-i passwd/user-fullname string Marvin Test Forge
d-i passwd/username string {DEBIAN_USERNAME}
d-i passwd/user-password-crypted password !
d-i partman-auto/method string regular
d-i partman-auto/disk string /dev/sda
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true
d-i apt-setup/non-free-firmware boolean true
tasksel tasksel/first multiselect standard, ssh-server
d-i pkgsel/include string openssh-server ca-certificates curl git sudo python3 python3-venv build-essential shellcheck bats hyperv-daemons
d-i pkgsel/upgrade select safe-upgrade
popularity-contest popularity-contest/participate boolean false
d-i grub-installer/only_debian boolean true
d-i finish-install/reboot_in_progress note
d-i preseed/late_command string \\
  in-target install -d -m 0700 -o {DEBIAN_USERNAME} -g {DEBIAN_USERNAME} /home/{DEBIAN_USERNAME}/.ssh ; \\
  echo '{public_text} marvin-test-forge' > /target/home/{DEBIAN_USERNAME}/.ssh/authorized_keys ; \\
  in-target chown {DEBIAN_USERNAME}:{DEBIAN_USERNAME} /home/{DEBIAN_USERNAME}/.ssh/authorized_keys ; \\
  in-target chmod 0600 /home/{DEBIAN_USERNAME}/.ssh/authorized_keys ; \\
  echo 'PasswordAuthentication no' > /target/etc/ssh/sshd_config.d/99-marvin-test-forge.conf ; \\
  echo 'PermitRootLogin no' >> /target/etc/ssh/sshd_config.d/99-marvin-test-forge.conf ; \\
  in-target deluser {DEBIAN_USERNAME} sudo || true ; \\
  echo '#!/bin/sh' > /target/usr/local/sbin/marvin-test-forge-runner ; \\
  echo 'set -eu' >> /target/usr/local/sbin/marvin-test-forge-runner ; \\
  echo 'if [ "${{1-}}" = "--version" ]; then echo 1; exit 0; fi' >> /target/usr/local/sbin/marvin-test-forge-runner ; \\
  echo 'case "${{1-}}" in linux-forge-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;; *) exit 64 ;; esac' >> /target/usr/local/sbin/marvin-test-forge-runner ; \\
  echo 'root="/var/tmp/$1"' >> /target/usr/local/sbin/marvin-test-forge-runner ; \\
  echo '[ -d "$root" ] && [ ! -L "$root" ] && [ -f "$root/run.sh" ] && [ ! -L "$root/run.sh" ] || exit 65' >> /target/usr/local/sbin/marvin-test-forge-runner ; \\
  echo 'cd "$root"; /bin/bash ./run.sh' >> /target/usr/local/sbin/marvin-test-forge-runner ; \\
  in-target chown root:root /usr/local/sbin/marvin-test-forge-runner ; \\
  in-target chmod 0750 /usr/local/sbin/marvin-test-forge-runner ; \\
  echo '{DEBIAN_USERNAME} ALL=(root) NOPASSWD: /usr/local/sbin/marvin-test-forge-runner, /usr/bin/systemctl poweroff' > /target/etc/sudoers.d/marvin-test-forge ; \\
  in-target chmod 0440 /etc/sudoers.d/marvin-test-forge
"""
    work_directory.mkdir(parents=True, exist_ok=True)
    preseed_path = work_directory / "preseed.cfg"
    _atomic_write(preseed_path, preseed)
    metadata_path = work_directory / "metadata.json"
    _metadata(metadata_path, {
        "profile": "debian13", "created_at": time.time(), "username": DEBIAN_USERNAME,
        "authentication": "ssh_ed25519_dpapi", "private_key_persisted_in_clear": False,
        "preseed_contains_secret": False,
    })
    return {
        "preseed_path": str(preseed_path), "metadata_path": str(metadata_path),
        "username": DEBIAN_USERNAME, "public_key": public_text,
        "secret_key": DEBIAN_KEY_SECRET,
    }


def prepare_windows(work_directory: Path, *, image_index: int) -> dict[str, Any]:
    """Create a transient Windows answer file and protect its password with DPAPI."""
    if image_index < 1 or image_index > 100:
        raise VMUnattendedError("Index d'image Windows invalide.")
    password = _new_password()
    admin_password = _new_password()
    dpapi_secret_store.set_secret(WINDOWS_PASSWORD_SECRET, password)
    dpapi_secret_store.set_secret(WINDOWS_ADMIN_PASSWORD_SECRET, admin_password)
    escaped_password = html.escape(password)
    escaped_admin_password = html.escape(admin_password)
    answer = f"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <SetupUILanguage><UILanguage>fr-FR</UILanguage></SetupUILanguage>
      <InputLocale>040c:0000040c</InputLocale><SystemLocale>fr-FR</SystemLocale><UILanguage>fr-FR</UILanguage><UserLocale>fr-FR</UserLocale>
    </component>
    <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <DiskConfiguration><Disk wcm:action="add"><DiskID>0</DiskID><WillWipeDisk>true</WillWipeDisk>
        <CreatePartitions>
          <CreatePartition wcm:action="add"><Order>1</Order><Type>EFI</Type><Size>260</Size></CreatePartition>
          <CreatePartition wcm:action="add"><Order>2</Order><Type>MSR</Type><Size>16</Size></CreatePartition>
          <CreatePartition wcm:action="add"><Order>3</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
        </CreatePartitions>
        <ModifyPartitions>
          <ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>FAT32</Format><Label>System</Label></ModifyPartition>
          <ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>3</PartitionID><Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter></ModifyPartition>
        </ModifyPartitions><WillShowUI>OnError</WillShowUI>
      </Disk></DiskConfiguration>
      <ImageInstall><OSImage><InstallFrom><MetaData wcm:action="add"><Key>/IMAGE/INDEX</Key><Value>{image_index}</Value></MetaData></InstallFrom><InstallTo><DiskID>0</DiskID><PartitionID>3</PartitionID></InstallTo><WillShowUI>OnError</WillShowUI></OSImage></ImageInstall>
      <UserData><AcceptEula>true</AcceptEula><FullName>Marvin Test Forge</FullName><Organization>Marvin</Organization><ProductKey><Key>VK7JG-NPHTM-C97JM-9MPGT-3V66T</Key><WillShowUI>Never</WillShowUI></ProductKey></UserData>
      <DynamicUpdate><Enable>false</Enable><WillShowUI>OnError</WillShowUI></DynamicUpdate>
    </component>
  </settings>
  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><ComputerName>MARVIN-WIN11</ComputerName><TimeZone>Romance Standard Time</TimeZone></component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-International-Core" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><InputLocale>040c:0000040c</InputLocale><SystemLocale>fr-FR</SystemLocale><UILanguage>fr-FR</UILanguage><UserLocale>fr-FR</UserLocale></component>
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <AutoLogon><Enabled>true</Enabled><LogonCount>1</LogonCount><Username>{WINDOWS_USERNAME}</Username><Password><Value>{escaped_password}</Value><PlainText>true</PlainText></Password></AutoLogon>
      <OOBE><HideEULAPage>true</HideEULAPage><HideOnlineAccountScreens>true</HideOnlineAccountScreens><HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE><NetworkLocation>Work</NetworkLocation><ProtectYourPC>3</ProtectYourPC></OOBE>
      <UserAccounts><LocalAccounts>
        <LocalAccount wcm:action="add"><Name>{WINDOWS_USERNAME}</Name><DisplayName>Marvin Test Forge</DisplayName><Group>Users</Group><Password><Value>{escaped_password}</Value><PlainText>true</PlainText></Password></LocalAccount>
        <LocalAccount wcm:action="add"><Name>{WINDOWS_ADMIN_USERNAME}</Name><DisplayName>Marvin Lab Administrator</DisplayName><Group>Administrators</Group><Password><Value>{escaped_admin_password}</Value><PlainText>true</PlainText></Password></LocalAccount>
      </LocalAccounts></UserAccounts>
      <RegisteredOwner>Marvin Test Forge</RegisteredOwner><TimeZone>Romance Standard Time</TimeZone>
    </component>
  </settings>
</unattend>
"""
    work_directory.mkdir(parents=True, exist_ok=True)
    answer_path = work_directory / "Autounattend.xml"
    _atomic_write(answer_path, answer)
    metadata_path = work_directory / "metadata.json"
    _metadata(metadata_path, {
        "profile": "windows11", "created_at": time.time(), "username": WINDOWS_USERNAME,
        "admin_username": WINDOWS_ADMIN_USERNAME,
        "image_index": image_index, "authentication": "random_password_dpapi",
        "answer_file_contains_transient_secret": True, "must_destroy_after_installation": True,
    })
    password = ""
    admin_password = ""
    return {
        "answer_path": str(answer_path), "metadata_path": str(metadata_path),
        "username": WINDOWS_USERNAME, "secret_key": WINDOWS_PASSWORD_SECRET,
        "admin_username": WINDOWS_ADMIN_USERNAME, "admin_secret_key": WINDOWS_ADMIN_PASSWORD_SECRET,
        "contains_transient_secret": True,
    }
