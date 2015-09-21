#!/bin/sh -e
#

echo "startup"
echo "startup" > /home/pi/Desktop/log

lsusb | grep -q '17e9:401b' && found=true

if [ $found ]; then
	echo "found"
	echo "found" >> /home/pi/Desktop/log
else
	echo "not found"
	echo "not found" >> /home/pi/Desktop/log
fi

echo "done"
echo "done" >> /home/pi/Desktop/log