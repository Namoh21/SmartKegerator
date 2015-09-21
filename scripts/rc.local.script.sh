#!/bin/sh -e
#
# Mimo auto configuration script

echo "Booting up!"
echo "Booting up!" >> /home/pi/Desktop/log

# Check to see if we have a mimo attached
lsusb | grep -q '17e9:401a' && found=true

if [ $found ]; then
	if [ -e /etc/X11/xorg.conf ]; then
		echo "Already setup for mimo"
		echo "Already setup for mimo" >> /home/pi/Desktop/log
	else
		echo "Mimo detected. Copying xorg files"
		echo "Mimo detected. Copying xorg files" >> /home/pi/Desktop/log
		cp -f /etc/X11/xorg-mimo.conf /etc/X11/xorg.conf
		sudo cp -f /boot/cmdline-touch.txt /boot/cmdline.txt
		echo "Rebooting"
		echo "Rebooting" >> /home/pi/Desktop/log
		sudo reboot
	fi
else
	if [ -e /etc/X11/xorg.conf ]; then
		echo "No mimo detected. Removing xorg files"
		echo "No mimo detected. Removing xorg files" >> /home/pi/Desktop/log
		rm -f /etc/X11/xorg.conf
		sudo cp -f /boot/cmdline-orig.txt /boot/cmdline.txt
		echo "Rebooting"
		echo "Rebooting" >> /home/pi/Desktop/log
		sudo reboot
	else
		echo "Already setup for hdmi"
		echo "Already setup for hdmi" >> /home/pi/Desktop/log
	fi
fi
