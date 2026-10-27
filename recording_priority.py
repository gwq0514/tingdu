"""Cooperative background pause: live capture and received audio take priority."""
import threading
import time

class RecordingPriority:
    def __init__(self, lease_seconds=20, clock=time.monotonic):
        self.condition=threading.Condition()
        self.leases={}
        self.pending={}
        self.lease_seconds=lease_seconds
        self.clock=clock

    def start(self,jid):
        with self.condition:
            self.leases[jid]=self.clock()+self.lease_seconds
            self.condition.notify_all()

    def enqueue(self,jid):
        with self.condition:
            self.leases[jid]=self.clock()+self.lease_seconds
            self.pending[jid]=self.pending.get(jid,0)+1
            self.condition.notify_all()

    def completed(self,jid):
        with self.condition:
            count=self.pending.get(jid,0)-1
            if count>0:self.pending[jid]=count
            else:self.pending.pop(jid,None)
            self.condition.notify_all()

    def stop(self,jid):
        with self.condition:
            self.leases.pop(jid,None)
            self.condition.notify_all()

    def _busy(self):
        now=self.clock()
        self.leases={jid:deadline for jid,deadline in self.leases.items() if deadline>now}
        return bool(self.leases or self.pending)

    def busy(self):
        with self.condition:return self._busy()

    def wait_for_background(self):
        with self.condition:
            while self._busy():
                # A closed page must not pause videos indefinitely. Already received
                # audio retains priority until its transcription actually completes.
                wait=max(.01,min(self.leases.values())-self.clock()) if self.leases else None
                self.condition.wait(wait)
