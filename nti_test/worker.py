import socket
import random
import time
import json
from queue import Queue, Full
import threading

class SystemClock:
    def __init__(self):
        self.start_time = time.time()

    def get_elapsed_time(self):
        return time.time() - self.start_time

class WorkerNode:
    def __init__(self, master_host, master_port):
        self.worker_id = None  # Master Node에서 할당받은 Worker ID
        self.master_host = master_host
        self.master_port = master_port
        self.system_clock = SystemClock()
        self.task_queue = Queue(maxsize=10)  # 작업 큐, 최대 10개의 작업만 허용
        self.success_count = 0
        self.failure_count = 0

    def connect_to_master(self):
        # Master Node에 연결
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_socket.connect((self.master_host, self.master_port))
        print(f"Master Node와 연결 {self.master_host}:{self.master_port}")

        # Worker ID 할당받기 (Master Node에서 할당)
        self.worker_id = ""
        buffer = ""  # 데이터 버퍼
        while True:
            data = self.client_socket.recv(1024).decode()
            buffer += data
            if "<END>" in buffer:
                self.worker_id = buffer.split("<END>")[0]  # 구분자를 기준으로 Worker ID 할당
                break
        print(f"Worker ID 할당: {self.worker_id}")

    def receive_task(self):
        buffer = ""  # 데이터 버퍼
        print('Master Node로부터 작업 수신 시작')
        while True:
            try:
                task_data = self.client_socket.recv(1024).decode()  # 작업 수신
                
                if task_data:
                    buffer += task_data  # 버퍼에 데이터 추가
                    if "<END>" in buffer:  # 구분자 확인
                        complete_task = buffer.split("<END>")[0]  # 구분자를 기준으로 작업 분리
                        buffer = buffer.split("<END>")[1]  # 나머지 데이터는 버퍼에 저장

                        # 작업에서 C[i,j] 값을 추출
                        try:
                            task_json = json.loads(complete_task)
                            i, j = task_json['i'], task_json['j']  # C[i, j] 값을 추출
                        except (json.JSONDecodeError, KeyError) as e:
                            print(f"작업 데이터 파싱 오류: {e}")
                            continue

                        # 큐가 가득 찬 경우 작업 실패 처리
                        try:
                            self.task_queue.put(complete_task, timeout=1)  # 큐에 작업을 추가
                            print(f"작업 수신 성공: {self.worker_id} / C[{i}, {j}]")

                            # 남은 큐 공간 계산
                            queue_remaining = self.task_queue.maxsize - self.task_queue.qsize()
                            print(queue_remaining, self.task_queue.qsize())
                            # 성공 메시지를 worker_id와 좌표 정보(i, j) 및 남은 큐 공간 정보로 구성
                            success_message = json.dumps({
                                "worker_id": self.worker_id,
                                "status": "received",
                                "task": f"C[{i}, {j}]",
                                "queue_remaining": queue_remaining
                            }) + "<END>"

                            # 성공 메시지 전송
                            self.client_socket.sendall(success_message.encode('utf-8'))

                        except Full:
                            # 큐가 가득 찬 경우 작업 실패 메시지 생성 및 전송
                            print(f"작업 실패: {self.worker_id}의 큐가 가득 참 C[{i},{j}]")
                            self.failure_count += 1

                            # 남은 큐 공간 계산
                            queue_remaining = self.task_queue.maxsize - self.task_queue.qsize()

                            # 실패 메시지를 worker_id와 좌표 정보(i, j) 및 남은 큐 공간 정보로 구성
                            failure_message = json.dumps({
                                "worker_id": self.worker_id,
                                "status": "failed",
                                "task": f"C[{i}, {j}]",
                                "queue_remaining": queue_remaining
                            }) + "<END>"

                            # 실패 메시지 전송
                            self.client_socket.sendall(failure_message.encode('utf-8'))

            except Exception as e:
                print(f"Error receiving task: {e}")
                break

    def process_task(self):
        while True:
            if not self.task_queue.empty():
                task_data = self.task_queue.get()  # 작업 큐에서 작업 꺼내기

                # json으로 전달된 데이터를 역직렬화하여 처리
                task = json.loads(task_data)
                i, j, A_row, B_col = task['i'], task['j'], task['A_row'], task['B_col']

                print(f"작업 처리: {self.worker_id} / C[{i}, {j}]")

                try:
                    # 작업 처리 (랜덤하게 1~3초 소요되는 작업 시뮬레이션)
                    time.sleep(random.uniform(1, 3))

                    # A_row와 B_col을 곱해서 C[i, j] 값을 계산
                    result = sum(a * b for a, b in zip(A_row, B_col))  # 행렬 곱 연산

                    # 남은 큐 공간 계산
                    queue_remaining = self.task_queue.maxsize - self.task_queue.qsize()

                    # 연산 성공/실패 확률 적용 (80% 성공, 20% 실패)
                    if random.random() < 0.8:
                        # 성공 시: C[i, j]와 연산 결과를 포함한 메시지를 전송
                        success_message = json.dumps({
                            "worker_id": self.worker_id,
                            "status": "success",
                            "task": f"C[{i}, {j}]",
                            "result": result,
                            "queue_remaining": queue_remaining
                        }) + "<END>"

                        print(f"{self.worker_id} 작업 성공: C[{i}, {j}] = {result}")
                        self.client_socket.sendall(success_message.encode('utf-8'))
                        self.success_count += 1
                    else:
                        raise Exception("Random failure occurred")

                except Exception as e:
                    # 작업 실패 시 Master Node에 실패 메시지 전송 (작업 재할당을 위해)
                    queue_remaining = self.task_queue.maxsize - self.task_queue.qsize()
                    failure_message = json.dumps({
                        "worker_id": self.worker_id,
                        "status": "failed",
                        "task": f"C[{i}, {j}]",
                        "queue_remaining": queue_remaining
                    }) + "<END>"

                    self.client_socket.sendall(failure_message.encode('utf-8'))
                    print(f"{self.worker_id} 작업 실패: C[{i}, {j}], {e}")
                    self.failure_count += 1

    def run(self):
        # Master Node와 연결
        self.connect_to_master()

        # 작업 수신 및 처리 스레드를 생성
        threading.Thread(target=self.receive_task).start()  # 작업 수신 스레드
        threading.Thread(target=self.process_task).start()  # 작업 처리 스레드

# Worker Node 실행
if __name__ == "__main__":
    worker_node = WorkerNode(master_host="127.0.0.1", master_port=9999)
    worker_node.run()
