#!/bin/bash
rm /etc/locale.conf
/usr/sbin/dpkg-reconfigure locales --frontend gnome
