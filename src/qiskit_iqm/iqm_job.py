# Copyright 2022 Qiskit on IQM developers
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Circuit execution jobs.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date

import numpy as np
from iqm_client.iqm_client import RunResult, RunStatus
from qiskit.providers import JobStatus, JobV1
from qiskit.result import Counts, Result

from qiskit_iqm.qiskit_to_iqm import MeasurementKey


class IQMJob(JobV1):
    """Implementation of Qiskit's job interface to handle circuit execution on an IQM server.

    Args:
        backend: the backend instance initiating this job
        job_id: string representation of the UUID generated by IQM server
        **kwargs: arguments to be passed to the initializer of the parent class
    """
    def __init__(self, backend: 'qiskit_iqm.IQMBackend', job_id: str, **kwargs):
        super().__init__(backend, job_id=job_id, **kwargs)
        self._result = None
        self._client = backend.client

    def _format_iqm_result(self, iqm_result: RunResult) -> list[str]:
        """Convert the measurement results from a circuit run into the Qiskit format.
        """
        # if not available in the metadata, use the number of shots in an arbitrary measurement
        shots = self.metadata.get('shots', len(next(iter(iqm_result.measurements.values()))))
        shape = (shots, 1)  # only one qubit is measured per measurement op

        measurements = {}
        for k, v in iqm_result.measurements.items():
            mk = MeasurementKey.from_string(k)
            res = np.array(v, dtype=int)

            if res.shape != shape:
                raise ValueError(f'Measurement result {mk} has the wrong shape {res.shape}, expected {shape}')
            res = res[:, 0]

            # group the measurements into cregs, fill in zeros for unused bits
            creg = measurements.setdefault(mk.creg_idx, np.zeros((shots, mk.creg_len), dtype=int))
            creg[:, mk.clbit_idx] = res

        # 1. Loop over the registers in the reverse order they were added to the circuit.
        # 2. Within each register the highest index is the most significant, so it goes to the leftmost position.
        return [
            ' '.join(
                ''.join(map(str, res[s, ::-1])) for _, res in sorted(measurements.items(), reverse=True)
            ) for s in range(shots)
        ]

    def submit(self):
        raise NotImplementedError('Instead, use IQMBackend.run to submit jobs.')

    def cancel(self):
        raise NotImplementedError('Canceling jobs is currently not supported.')

    def result(self) -> Result:
        if not self._result:
            result = self._client.wait_for_results(uuid.UUID(self._job_id))
            self._result = self._format_iqm_result(result)

        result_dict = {
            'backend_name': None,
            'backend_version': None,
            'qobj_id': None,
            'job_id': self._job_id,
            'success': True,
            'results': [
                {
                    'shots': len(self._result),
                    'success': True,
                    'data': {'memory': self._result, 'counts': Counts(Counter(self._result))}
                }
            ],
            'date': date.today()
        }
        return Result.from_dict(result_dict)

    def status(self) -> JobStatus:
        if self._result:
            return JobStatus.DONE

        result = self._client.get_run(uuid.UUID(self._job_id))
        if result.status == RunStatus.READY:
            self._result = self._format_iqm_result(result)
            return JobStatus.DONE
        return JobStatus.RUNNING