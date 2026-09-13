CC = gcc
CFLAGS = -Wall -Wextra -O2
TARGET = device_sim

all: $(TARGET)

$(TARGET): main.c protocol.h
	$(CC) $(CFLAGS) main.c -o $(TARGET)

clean:
	rm -f $(TARGET)