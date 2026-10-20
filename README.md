<p align="center"><img src="plasma/config/includes.chroot/etc/calamares/branding/driftwood/welcome.png" alt="Driftwood" width="320"></p>

# Driftwood

A live/installable **Debian stable + KDE Plasma** image. Everything comes from
Debian's own archive, apart from Firefox (Mozilla's apt repository) and the
VirtualBox guest additions (Debian Fast Track). Installed systems track
`stable`, so they move to each new Debian release with a normal upgrade.

## What's in it

- **Debian 13 "trixie"**, KDE Plasma 6, with kernel and firmware from Debian backports.
- **Btrfs with bootable snapshots.** Snapper takes a snapshot before and after
  every apt run, and GRUB lists them. Each snapshot keeps a copy of the kernel
  it was taken with, so it can still boot after apt has removed that kernel.
  `snapper-rollback` makes a snapshot the live system again.
  - Subvolumes: `@`, `@home`, `@root`, `@var@log`, `@var@cache`, `@var@tmp`, `@snapshots`.
  - zstd compression; `/tmp` on tmpfs.
- **Full-disk encryption** with LUKS2/argon2id, asking for the passphrase
  once. `/boot` is a separate unencrypted partition, so GRUB never decrypts anything.
- **Calamares 3.3 installer.** `tools/check-calamares.py` checks its configs against the upstream schemas.
- Flatpak (Flathub) through Discover, firmware updates through fwupd, PipeWire,
  TLP, zram swap, proprietary codecs and firmware.

## Building

The ISO is built on GitHub Actions (`.github/workflows/build.yml`) on every
push to `main`:

1. **checks:** package lists resolve against trixie, Calamares configs
   validate, and the unit tests in `tests/` pass.
2. **build:** live-build runs in a `debian:trixie` container. The run fails if the ISO is 2 GiB or bigger (the GitHub
   release-asset limit). The ISO and its checksum are uploaded as artifacts.
3. **boot:** QEMU/KVM boots the ISO three ways:
   - the kernel directly with a serial console, until Plasma is up;
   - UEFI through GRUB;
   - BIOS through isolinux.
   Screenshots and logs are kept.

To build locally (Debian trixie, root):

```sh
docker run --rm --privileged -v "$PWD:/src" -w /src debian:trixie ci/build-iso.sh
# -> out/Driftwood_Plasma_<version>_x86-64.iso
```

## Layout

```
plasma/      live-build config (auto/, config/), build.sh
ci/          build-iso.sh (container build), boot-test.py (QEMU)
tests/       unit tests for the installer job, snapshot plugin, GRUB menu, rollback
tools/       package-list and Calamares config checks, size estimates
artwork/     logo source and the script that renders all branded images
```

## Credits

Driftwood started as a fork of **[SpiralLinux](https://github.com/SpiralLinux/SpiralLinux-project)**
by its original author. Most of the system configuration is SpiralLinux's work, carried over from its
Debian 12 Plasma spin:
- the package selection and desktop defaults;
- the Btrfs/Snapper/grub-btrfs setup and `snapper-rollback`;
- PipeWire tuning, the live-config hooks, and the Calamares setup.

Driftwood ports it to Debian 13 and Calamares 3.3, trims it to fit a single
ISO under 2 GiB, and adds the encryption, snapshot-boot and CI work described above.
The upstream project's history and Debian 12 images remain at
https://github.com/SpiralLinux/SpiralLinux-project.

Also used:
- [grub-btrfs](https://github.com/Antynea/grub-btrfs) (GPL-3.0, its own LICENSE in
  `plasma/config/includes.chroot/usr/share/grub-btrfs/`);
- [snapper-rollback](https://github.com/jrabinow/snapper-rollback), with changes
  credited in the script.

## Artwork

- **Logo** (`artwork/logo.svg`): made for Driftwood and released under
  [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
- **Wallpaper and installer photo:** "Driftwood amongst the grasses at the head of
  Captain Cove", British Columbia, by
  [Extemporalist](https://commons.wikimedia.org/wiki/File:Driftwood_amongst_the_grasses_at_the_head_of_Captain_Cove.webp),
  CC0 1.0, via Wikimedia Commons.

`artwork/make_art.py` regenerates every branded image (boot splash, installer
welcome, slideshow, logo PNG, wallpaper) from these two sources.
