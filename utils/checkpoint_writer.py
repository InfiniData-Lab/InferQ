import threading
import queue
import logging

logger = logging.getLogger(__name__)


class AsyncCheckpointWriter:
    def __init__(self, filepath, batch_size=20):
        self.filepath = filepath
        self.batch_size = batch_size
        self.buffer = []
        self.queue = queue.Queue()
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def add(self, item):
        self.buffer.append(item)
        if len(self.buffer) >= self.batch_size:
            self._flush_buffer()

    def _flush_buffer(self):
        if self.buffer:
            self.queue.put(list(self.buffer))
            self.buffer = []

    def _worker(self):
        while self.running or not self.queue.empty():
            try:
                batch = self.queue.get(timeout=0.5)
                self._write_batch(batch)
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Checkpoint worker error: {e}")

    def _write_batch(self, batch):
        try:
            with open(self.filepath, "a") as f:
                f.write("\n".join(batch) + "\n")
        except Exception as e:
            logger.error(f"Failed to write checkpoint batch: {e}")

    def close(self):
        self._flush_buffer()
        self.running = False
        self.worker_thread.join()
