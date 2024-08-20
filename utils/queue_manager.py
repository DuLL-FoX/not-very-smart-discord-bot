class QueueManager:
    def __init__(self):
        self.queue = []

    def add_to_queue(self, info):
        self.queue.append({"info": info})

    def extend_queue(self, entries):
        self.queue.extend([{"info": entry} for entry in entries])

    def get_next(self):
        return self.queue.pop(0) if self.queue else None

    def clear_queue(self):
        self.queue.clear()

    def is_empty(self):
        return not bool(self.queue)