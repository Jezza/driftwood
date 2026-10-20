#!/bin/bash
# Language support menu. Loops until the user closes or cancels the dialog.

while ans=$(kdialog --title "Language support configuration" \
	--menu "What to do?" \
	locales "Set system language(s)" \
	packs "Install language packs" 2>/dev/null); do
	case "$ans" in
		locales) pkexec /usr/sbin/reconfigure-locales-wrapper.sh ;;
		packs) pkexec /usr/sbin/synaptic --update-at-startup -i=Languages ;;
	esac
done
