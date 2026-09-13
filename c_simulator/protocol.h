#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stdint.h>

#define DEFAULT_PORT 8888

// Message Types
typedef enum {
    MSG_GET_INFO     = 0x01,
    MSG_EXECUTE_STAGE = 0x02,
    MSG_READ_FILE     = 0x03,
    MSG_RESPONSE      = 0x04
} msg_type_t;

// Status Codes
typedef enum {
    STATUS_OK           = 0,
    STATUS_STAGE_FAILED = 1,
    STATUS_FILE_NOT_FOUND = 2,
    STATUS_ERROR        = 99
} status_code_t;

#pragma pack(push, 1)
typedef struct {
    uint8_t msg_type;
    uint32_t payload_len;
} MessageHeader;

typedef struct {
    uint8_t battery_level;
    uint16_t ios_version_major;
    uint16_t ios_version_minor;
    char model[32];
} DeviceInfoPayload;

typedef struct {
    uint8_t stage_id;
} ExecuteStagePayload;

typedef struct {
    uint32_t status;
    uint32_t data_len;
} ResponseHeader;
#pragma pack(pop)

#endif // PROTOCOL_H