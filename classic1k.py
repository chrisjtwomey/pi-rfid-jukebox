import time
import math
import ndef
import board
import busio
import logging
from adafruit_pn532.adafruit_pn532 import MIFARE_CMD_AUTH_B
from adafruit_pn532.i2c import PN532_I2C


class Classic1kError(Exception):
    def __init__(self, message):
        super().__init__(message)


class Classic1k:
    DEFAULT_KEY_B = b"\xFF\xFF\xFF\xFF\xFF\xFF"
    TLV_TERM = 0xFE  # tlv terminator
    START_BLOCK = 4
    BLOCK_SIZE = 16
    BLOCKS_PER_SECTOR = 4
    MAX_SECTORS = 16
    LONG_TLV_SIZE = 4
    SHORT_TLV_SIZE = 2

    def __init__(self, timeout=2):
        self.log = logging.getLogger(self.__class__.__name__)
        try:
            # I2C connection:
            i2c = busio.I2C(board.SCL, board.SDA)

            # Non-hardware reset/request with I2C
            pn532 = PN532_I2C(i2c, debug=False)

            _, ver, rev, _ = pn532.firmware_version
            self.log.debug(
                "found PN532 with firmware version: {0}.{1}".format(ver, rev)
            )

            # Configure PN532 to communicate with MiFare cards
            pn532.SAM_configuration()
        except Exception as e:
            raise Classic1kError("failed to init PN532 reader: " + str(e))

        self.pn532 = pn532
        self.timeout = timeout

    def check_for_uid(self, timeout=1):
        return self.pn532.read_passive_target(timeout=timeout)

    def wait_for_uid(self):
        uid = self.check_for_uid(self.timeout)
        while uid is None:
            uid = self.check_for_uid(self.timeout)

        return uid

    def write_uri(self, uid, uri):
        records = [ndef.UriRecord(uri)]
        encoded = b"".join(ndef.message_encoder(records))

        self._write(uid, encoded)

    def read_uri(self, uid):
        data = self._read(uid)

        # try to parse the ndef msg inside
        try:
            decoder = ndef.message_decoder(data)
            record = next(decoder)
        except Exception as e:
            raise Classic1kError(
                "Failed to parse NDEF records from card data: " + str(e)
            )

        return record.iri

    def format(self, uid):
        self.log.info("formatting card...")

        for curr_block in range(
            self.START_BLOCK, self.BLOCKS_PER_SECTOR * self.MAX_SECTORS
        ):
            _, sb = self._calc_sector_block(curr_block)

            # is first block in sector
            if sb == 0:
                # authenticate at start of every sector
                if not self.pn532.mifare_classic_authenticate_block(
                    uid, curr_block, MIFARE_CMD_AUTH_B, self.DEFAULT_KEY_B
                ):
                    raise Classic1kError(
                        "authentication failed for block {}".format(curr_block)
                    )

            # is sector trailer
            if sb == 3:
                continue

            buf = [0x00] * self.BLOCK_SIZE
            if not self.pn532.mifare_classic_write_block(curr_block, buf):
                raise Classic1kError("write failed for block {}".format(curr_block))

    def _read(self, uid):
        self.log.info("begin card read...")
        curr_block = self.START_BLOCK

        if not self.pn532.mifare_classic_authenticate_block(
            uid, curr_block, MIFARE_CMD_AUTH_B, self.DEFAULT_KEY_B
        ):
            raise Classic1kError("authentication failed reading TLV")

        data = self.pn532.mifare_classic_read_block(curr_block)
        valid, msg_len, msg_start_idx = self._decode_tlv(data)
        if not valid:
            raise Classic1kError("invalid TLV in message")

        idx = 0
        buffer_size = self._get_buffer_size(msg_len)

        data = bytearray()
        while idx < buffer_size:
            _, sb = self._calc_sector_block(curr_block)

            # is first block in sector
            if sb == 0:
                # authenticate at start of every sector
                if not self.pn532.mifare_classic_authenticate_block(
                    uid, curr_block, MIFARE_CMD_AUTH_B, self.DEFAULT_KEY_B
                ):
                    raise Classic1kError(
                        "authentication failed for block {}".format(curr_block)
                    )

            # is sector trailer
            if sb == 3:
                curr_block += 1
                continue

            buf = self.pn532.mifare_classic_read_block(curr_block)
            if buf is None:
                raise Classic1kError(
                    "received unexpected data from block {}: {}".format(curr_block, buf)
                )

            term_idx = buf.find(self.TLV_TERM)
            if term_idx >= 0:
                if term_idx == len(buf) - 1:
                    data += buf[:term_idx]
                else:
                    data += buf[: term_idx + 1]
                break
            else:
                data += buf
                idx += len(buf)

            curr_block += 1

        self._dump_to_log(data)
        # trim to start of NDEF msg
        data = data[msg_start_idx:]

        return data

    def _write(self, uid, data):
        self.log.info("begin card write...")

        buf = bytearray()
        # prepend header bytes
        if len(data) <= 0xFF:
            buf.append(0x00)
            buf.append(0x00)
            buf.append(0x03)
            buf.append(len(data))
            buf.extend(data)
            buf.append(self.TLV_TERM)
        else:
            buf.append(0x03)
            buf.append(0xFF)
            buf.append(((len(data) >> 8) & 0xFF))
            buf.append((len(data) & 0xFF))
            buf.extend(data)
            buf.append(self.TLV_TERM)

        self._dump_to_log(buf)

        curr_block = self.START_BLOCK
        chunks = bytearray_chunker(buf, self.BLOCK_SIZE)
        while len(chunks) > 0:
            _, sb = self._calc_sector_block(curr_block)

            # is first block in sector
            if sb == 0:
                # authenticate at start of every sector
                if not self.pn532.mifare_classic_authenticate_block(
                    uid, curr_block, MIFARE_CMD_AUTH_B, self.DEFAULT_KEY_B
                ):
                    raise Classic1kError(
                        "authentication failed for block {}".format(curr_block)
                    )

            # is sector trailer
            if sb == 3:
                curr_block += 1
                continue

            chunk = chunks.pop(0)
            if not self.pn532.mifare_classic_write_block(curr_block, chunk):
                raise Classic1kError("write failed for block {}".format(curr_block))

            curr_block += 1

    def _dump_to_log(self, data):
        self.log.debug("data dump:")
        curr_block = self.START_BLOCK
        for chunk in bytearray_chunker(data, self.BLOCK_SIZE):
            self.log.debug(self._fmt_block_buf(curr_block, chunk))
            curr_block += 1

    def _fmt_block_buf(self, block, buf):
        s, sb = self._calc_sector_block(block)
        fmt_block = "{:02} S{:02} B{:02}: {}".format(
            block, s, sb, " ".join(["{:02x}".format(b) for b in buf])
        )
        fmt_block += "  "
        for b in buf:
            if b > 0x20 and b < 0x7F:
                fmt_block += chr(b)
            else:
                fmt_block += "."
        return fmt_block

    def _calc_sector_block(self, block):
        return (
            math.floor(block / self.BLOCKS_PER_SECTOR),
            block % self.BLOCKS_PER_SECTOR,
        )

    def _get_ndef_start_idx(self, data):
        for i in range(self.BLOCK_SIZE):
            if data[i] == 0x00:
                continue
            if data[i] == 0x03:
                return i

            raise Classic1kError("unknown TLV")

    def _decode_tlv(self, data):
        i = self._get_ndef_start_idx(data)
        msg_len = 0
        msg_start_idx = 0

        if i < 0 or data[i] != 0x03:
            raise Classic1kError("cannot decode TLV message length")

        if data[i + 1] == 0xFF:
            msg_len = ((0xFF & data[i + 2]) << 8) | (0xFF & data[i + 3])
            msg_start_idx = i + self.LONG_TLV_SIZE

            return True, msg_len, msg_start_idx

        msg_len = data[i + 1]
        msg_start_idx = i + self.SHORT_TLV_SIZE

        return True, msg_len, msg_start_idx

    def _get_buffer_size(self, msg_len):
        buffer_size = msg_len

        if msg_len < 0xFF:
            buffer_size += self.SHORT_TLV_SIZE + 1
        else:
            buffer_size == self.LONG_TLV_SIZE + 1

        if buffer_size % self.BLOCK_SIZE != 0:
            buffer_size = ((buffer_size / self.BLOCK_SIZE) + 1) * self.BLOCK_SIZE

        return buffer_size


def bytearray_chunker(seq, size):
    # ensure non immutable
    seq = list(seq)

    chunks = []
    for pos in range(0, len(seq), size):
        chunk = seq[pos : pos + size]
        # pad with zeros so we're always returning size length chunks
        chunk.extend([0x00] * (size - len(chunk)))
        chunks.append(bytearray(chunk))

    return chunks
