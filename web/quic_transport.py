"""Authenticated TCP streams over standard QUIC (aioquic 1.9.2)."""
import asyncio
import hmac
from importlib.metadata import version
import ssl

from aioquic.asyncio import QuicConnectionProtocol, connect, serve
from aioquic.buffer import size_uint_var
from aioquic.quic import events
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.packet_builder import QuicPacketBuilderStop

if version("aioquic") != "1.9.2":
    raise ImportError("The QUIC adapter requires aioquic 1.9.2")

ALPN = "paqet-stream/1"
WINDOW = 1024 * 1024
KEY_SIZE = 43


def configuration(client, **options):
    return QuicConfiguration(is_client=client, alpn_protocols=[ALPN], idle_timeout=45,
                             congestion_control_algorithm="cubic", max_datagram_size=1200,
                             max_data=4 * WINDOW, max_stream_data=WINDOW, **options)


class StreamWriter:
    """Expose stream-level EOF and bound queued sends while QUIC awaits ACKs."""
    def __init__(self, protocol, stream_id):
        self.protocol = protocol
        self.stream_id = stream_id
        self.finished = False
        self.released = False

    def write(self, data):
        if self.finished or self.protocol.terminated or not self.protocol._quic.can_send_stream_data(self.stream_id):
            raise ConnectionError("QUIC stream closed")
        self.protocol._quic.send_stream_data(self.stream_id, data)
        self.protocol.transmit()

    async def drain(self):
        # aioquic's generic asyncio adapter does not backpressure its send buffer.
        # This sender buffer belongs to the pinned aioquic release.
        async def writable():
            while not self.protocol.terminated:
                stream = self.protocol._quic._streams.get(self.stream_id)
                if stream is None or stream.sender.is_finished:
                    raise ConnectionError("QUIC stream closed")
                if len(stream.sender._buffer) <= WINDOW:
                    return
                await asyncio.sleep(0.025)
            raise ConnectionError("QUIC transport closed")

        await asyncio.wait_for(writable(), 20)

    def can_write_eof(self):
        return True

    def write_eof(self):
        if not self.finished and not self.protocol.terminated:
            self.finished = True
            if self.protocol._quic.can_send_stream_data(self.stream_id):
                self.protocol._quic.send_stream_data(self.stream_id, b"", end_stream=True)
                self.protocol.transmit()

    def close(self):
        if self.released:
            return
        self.released = True
        self.write_eof()
        reader = self.protocol.readers.get(self.stream_id)
        if reader and not self.protocol.terminated:
            # Stop an incoming half if the local consumer closed before peer FIN.
            try:
                if not reader._eof:
                    self.protocol._quic.stop_stream(self.stream_id, 1)
                    self.protocol.transmit()
                    return
            except ValueError:
                pass
        self.protocol.release(self.stream_id)

    async def wait_closed(self):
        pass  # FIN delivery is driven by the shared QUIC socket.


def preserve_stream_fin(quic):
    write_frame = quic._write_stream_frame

    def guarded_write(builder, space, stream, max_offset):
        # aioquic 1.9.2 removes a FIN-only frame from its pending queue before
        # checking packet capacity. Flush a full packet before consuming that FIN.
        if stream.sender._pending_eof:
            offset = stream.sender.next_offset
            overhead = 3 + size_uint_var(stream.stream_id) + (size_uint_var(offset) if offset else 0)
            if min(builder.remaining_buffer_space, builder.remaining_flight_space) < overhead:
                raise QuicPacketBuilderStop
        return write_frame(builder, space, stream, max_offset)

    quic._write_stream_frame = guarded_write


class Protocol(QuicConnectionProtocol):
    def __init__(self, quic, stream_handler=None):
        super().__init__(quic)
        preserve_stream_fin(quic)
        self.is_client = quic.configuration.is_client
        self.handler = stream_handler
        self.readers = {}
        self.writers = {}
        self.terminated = False
        self.ready = False

    def release(self, stream_id):
        self.readers.pop(stream_id, None)
        self.writers.pop(stream_id, None)

    def stream(self, stream_id):
        reader = asyncio.StreamReader(limit=WINDOW)
        writer = StreamWriter(self, stream_id)
        self.readers[stream_id], self.writers[stream_id] = reader, writer
        return reader, writer

    def open_stream(self, key):
        stream_id = self._quic.get_next_available_stream_id()
        reader, writer = self.stream(stream_id)
        # The first write reserves the ID before another task can open a stream.
        writer.write(key.encode("ascii"))
        return reader, writer

    def quic_event_received(self, event):
        if isinstance(event, events.HandshakeCompleted):
            self.ready = event.alpn_protocol == ALPN
        elif isinstance(event, events.ConnectionTerminated):
            self.terminated = True
            for reader in self.readers.values():
                reader.set_exception(ConnectionError("QUIC transport closed"))
            self.readers.clear()
            self.writers.clear()
        elif isinstance(event, (events.StreamReset, events.StopSendingReceived)):
            reader = self.readers.get(event.stream_id)
            if reader:
                reader.set_exception(ConnectionError("QUIC stream reset"))
                if self.writers[event.stream_id].released:
                    self.release(event.stream_id)
        elif isinstance(event, events.StreamDataReceived):
            stream_id = event.stream_id
            reader = self.readers.get(stream_id)
            if reader is None:
                if self.is_client or not self.ready or stream_id % 4 != 0 or len(self.readers) >= 128:
                    self._quic.stop_stream(stream_id, 1)
                    if stream_id % 4 == 0:
                        self._quic.reset_stream(stream_id, 1)
                    return
                reader, writer = self.stream(stream_id)
                self.handler(reader, writer)
            writer = self.writers[stream_id]
            # Flow control inside aioquic permits new data when it is delivered,
            # so guard the consumer queue if the local TCP service stops reading.
            if not writer.released:
                if len(reader._buffer) + len(event.data) > 2 * WINDOW:
                    reader.set_exception(ConnectionError("QUIC receive queue full"))
                    writer.close()
                    return
                reader.feed_data(event.data)
            if event.end_stream:
                reader.feed_eof()
                if writer.released:
                    self.release(stream_id)


async def listen(host, port, accept, cert_chain, private_key):
    config = configuration(False)
    config.load_cert_chain(cert_chain, private_key)
    server = await serve(host, port, configuration=config, retry=True, create_protocol=Protocol,
                         stream_handler=lambda r, w: asyncio.create_task(accept(r, w)))
    return server, config


class Pool:
    """Reuse a verified TLS session for simultaneous TCP flows to each endpoint."""
    def __init__(self, cafile=None):
        self.cafile = cafile
        self.sessions = {}
        self.lock = asyncio.Lock()

    async def session(self, domain, port):
        endpoint = domain, port
        async with self.lock:
            pending = self.sessions.get(endpoint)
            if pending is None or pending.done() and (pending.cancelled() or pending.exception() is not None
                                                     or pending.result().terminated):
                pending = asyncio.create_task(self.dial(endpoint))
                self.sessions[endpoint] = pending
        return await asyncio.shield(pending)

    async def dial(self, endpoint):
        domain, port = endpoint
        task = asyncio.current_task()
        config = configuration(True, server_name=domain, verify_mode=ssl.CERT_REQUIRED, cafile=self.cafile)
        connection = connect(domain, port, configuration=config, create_protocol=Protocol)
        try:
            protocol = await asyncio.wait_for(connection.__aenter__(), 5)
        except BaseException:
            if self.sessions.get(endpoint) is task:
                self.sessions.pop(endpoint)
            raise
        asyncio.create_task(self.retire(endpoint, task, connection, protocol))
        return protocol

    async def retire(self, endpoint, task, connection, protocol):
        try:
            await protocol.wait_closed()
        finally:
            if self.sessions.get(endpoint) is task:
                self.sessions.pop(endpoint)
            await connection.__aexit__(None, None, None)

    async def open(self, peer):
        protocol = await self.session(peer["domain"], peer["port"])
        reader, writer = protocol.open_stream(peer["key"])
        try:
            reply = await asyncio.wait_for(reader.readexactly(1), 5)
            if reply != b"\x00":
                raise ConnectionError("QUIC receiver declined stream")
            return reader, writer
        except (Exception, asyncio.CancelledError) as error:
            writer.close()
            if isinstance(error, asyncio.IncompleteReadError):
                raise ConnectionError("QUIC receiver closed stream") from error
            raise


async def authenticate(reader, key):
    try:
        incoming = await asyncio.wait_for(reader.readexactly(KEY_SIZE), 4)
    except asyncio.IncompleteReadError:
        return False
    return hmac.compare_digest(incoming, key.encode("ascii"))
