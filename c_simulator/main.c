# include <stdio.h>
# include <stdlib.h>
# include <string.h>
# include <unistd.h>
# include <arpa/inet.h>
# include "protocol.h"

int
fail_at_stage = -1;
int
disconnect_at_stage = -1;

void
handle_client(int
client_fd) {
    MessageHeader
hdr;
while (recv(client_fd, & hdr, sizeof(MessageHeader), MSG_WAITALL) > 0) {
hdr.payload_len = ntohl(hdr.payload_len);

if (hdr.msg_type == MSG_GET_INFO) {
DeviceInfoPayload info = {.battery_level = 85, .ios_version_major = 16, .ios_version_minor = 5};
strncpy(info.model, "iPhone14,2", sizeof(info.model));

ResponseHeader resp = {.status = htonl(STATUS_OK), .data_len = htonl(sizeof(info))};
send(client_fd, & resp, sizeof(resp), 0);
send(client_fd, & info, sizeof(info), 0);

} else if (hdr.msg_type == MSG_EXECUTE_STAGE) {
ExecuteStagePayload stage_req;
recv(client_fd, & stage_req, sizeof(stage_req), MSG_WAITALL);

if (disconnect_at_stage == stage_req.stage_id) {
close(client_fd);
return;
}

ResponseHeader
resp;
if (fail_at_stage == stage_req.stage_id)
{
resp.status = htonl(STATUS_STAGE_FAILED);
resp.data_len = 0;
} else {
resp.status = htonl(STATUS_OK);
resp.data_len = 0;
}
send(client_fd, & resp, sizeof(resp), 0);

} else if (hdr.msg_type == MSG_READ_FILE) {
char path[256] = {0};
recv(client_fd, path, hdr.payload_len, MSG_WAITALL);

char dummy_data[] = "EXTRACTED_DEVICE_DATA_PAYLOAD";
ResponseHeader resp = {.status = htonl(STATUS_OK), .data_len = htonl(strlen(dummy_data))};
send(client_fd, & resp, sizeof(resp), 0);
send(client_fd, dummy_data, strlen(dummy_data), 0);
}
}
close(client_fd);
}

int main(int argc, char * argv[]) {
int port = DEFAULT_PORT;
for (int i = 1; i < argc; i++) {
if (strcmp(argv[i], "--fail-stage") == 0 & & i + 1 < argc) fail_at_stage = atoi(argv[++i]);
if (strcmp(argv[i], "--drop-stage") == 0 & & i + 1 < argc) disconnect_at_stage = atoi(argv[++i]);
if (strcmp(argv[i], "--port") == 0 & & i + 1 < argc) port = atoi(argv[++i]);
}

int server_fd = socket(AF_INET, SOCK_STREAM, 0);
int opt = 1;
setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, & opt, sizeof(opt));

struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons(port), .sin_addr.s_addr = INADDR_ANY};
bind(server_fd, (struct sockaddr * ) & addr, sizeof(addr));
listen(server_fd, 1);

while (1) {
int client_fd = accept(server_fd, NULL, NULL);
if (client_fd >= 0) handle_client(client_fd);
}
return 0;
}