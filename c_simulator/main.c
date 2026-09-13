#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#include "protocol.h"

static int fail_at_stage = -1;
static int disconnect_at_stage = -1;

/* Reads exactly `len` bytes into `buf`. Returns 1 on success, 0 if the
 * peer closed the connection or an error occurred before `len` bytes
 * were received. */
static int recv_exact(int fd, void *buf, size_t len) {
    if (len == 0) {
        return 1;
    }
    ssize_t n = recv(fd, buf, len, MSG_WAITALL);
    return n == (ssize_t)len;
}

static void handle_client(int client_fd) {
    MessageHeader hdr;

    while (recv_exact(client_fd, &hdr, sizeof(hdr))) {
        hdr.payload_len = ntohl(hdr.payload_len);

        switch (hdr.msg_type) {
        case MSG_GET_INFO: {
            DeviceInfoPayload info;
            memset(&info, 0, sizeof(info));
            info.battery_level = 85;
            info.ios_version_major = htons(16);
            info.ios_version_minor = htons(5);
            strncpy(info.model, "iPhone14,2", sizeof(info.model) - 1);

            ResponseHeader resp;
            resp.status = htonl(STATUS_OK);
            resp.data_len = htonl((uint32_t)sizeof(info));

            send(client_fd, &resp, sizeof(resp), 0);
            send(client_fd, &info, sizeof(info), 0);
            break;
        }

        case MSG_EXECUTE_STAGE: {
            ExecuteStagePayload stage_req;
            if (!recv_exact(client_fd, &stage_req, sizeof(stage_req))) {
                close(client_fd);
                return;
            }

            if (disconnect_at_stage == stage_req.stage_id) {
                close(client_fd);
                return;
            }

            ResponseHeader resp;
            resp.data_len = 0;
            if (fail_at_stage == stage_req.stage_id) {
                resp.status = htonl(STATUS_STAGE_FAILED);
            } else {
                resp.status = htonl(STATUS_OK);
            }
            send(client_fd, &resp, sizeof(resp), 0);
            break;
        }

        case MSG_READ_FILE: {
            char path[256];
            memset(path, 0, sizeof(path));

            size_t to_read = hdr.payload_len;
            if (to_read > sizeof(path) - 1) {
                to_read = sizeof(path) - 1;
            }
            if (!recv_exact(client_fd, path, to_read)) {
                close(client_fd);
                return;
            }

            const char dummy_data[] = "EXTRACTED_DEVICE_DATA_PAYLOAD";
            ResponseHeader resp;
            resp.status = htonl(STATUS_OK);
            resp.data_len = htonl((uint32_t)(sizeof(dummy_data) - 1));

            send(client_fd, &resp, sizeof(resp), 0);
            send(client_fd, dummy_data, sizeof(dummy_data) - 1, 0);
            break;
        }

        default:
            /* Unknown message type: drain nothing further and disconnect. */
            close(client_fd);
            return;
        }
    }

    close(client_fd);
}

int main(int argc, char *argv[]) {
    printf("[BUILD_VER_101] Device simulator starting...\n");
    fflush(stdout);

    int port = DEFAULT_PORT;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--fail-stage") == 0 && i + 1 < argc) {
            fail_at_stage = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--drop-stage") == 0 && i + 1 < argc) {
            disconnect_at_stage = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--port") == 0 && i + 1 < argc) {
            port = atoi(argv[++i]);
        }
    }

    /* A dropped connection (--drop-stage) makes a subsequent send() raise
     * SIGPIPE; ignore it so the write just fails with EPIPE instead of
     * killing the process. */
    signal(SIGPIPE, SIG_IGN);

    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        perror("socket");
        return EXIT_FAILURE;
    }

    int opt = 1;
    if (setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
        perror("setsockopt");
        close(server_fd);
        return EXIT_FAILURE;
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);

    if (bind(server_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(server_fd);
        return EXIT_FAILURE;
    }

    if (listen(server_fd, 1) < 0) {
        perror("listen");
        close(server_fd);
        return EXIT_FAILURE;
    }

    printf("Device simulator listening on port %d (fail_stage=%d, drop_stage=%d)\n",
           port, fail_at_stage, disconnect_at_stage);
    fflush(stdout);

    while (1) {
        int client_fd = accept(server_fd, NULL, NULL);
        if (client_fd >= 0) {
            handle_client(client_fd);
        }
    }

    close(server_fd);
    return EXIT_SUCCESS;
}
