"""会话池管理器"""
import asyncio
import logging
from typing import Optional
from h2ogpte_client import H2OGPTEClient

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, client: H2OGPTEClient, pool_size: int = 3, max_pool_size: int = 10):
        self.client = client
        self.target_pool_size = pool_size
        self.max_pool_size = max_pool_size
        self.queue = asyncio.Queue()
        self.cleanup_queue = asyncio.Queue()
        self.background_tasks = []
        self.running = False
        self._pool_lock = asyncio.Lock()

    async def start(self):
        """启动后台任务"""
        self.running = True
        self.background_tasks.append(asyncio.create_task(self._pool_maintainer()))
        self.background_tasks.append(asyncio.create_task(self._cleanup_worker()))
        logger.info("Session Manager started")

    async def stop(self):
        """停止后台任务"""
        self.running = False
        for task in self.background_tasks:
            task.cancel()
        
        # 清理剩余会话
        while not self.queue.empty():
            try:
                session_id = self.queue.get_nowait()
                await self.client.delete_chat_session(session_id)
            except Exception:
                pass
        logger.info("Session Manager stopped")

    async def get_session(self) -> str:
        """获取一个可用会话"""
        if self.queue.empty():
            logger.warning("Session pool empty, creating on-demand session")
            # 如果池空了，立即创建一个（这会阻塞用户，但比报错好）
            return await self.client.create_chat_session()
        
        session_id = await self.queue.get()
        logger.info(f"Acquired session from pool: {session_id} (Remaining: {self.queue.qsize()})")
        
        # 触发补充检查
        if self.queue.qsize() < self.target_pool_size:
            # 可以在这里发信号给 maintainer，或者依赖它的循环
            pass
            
        return session_id

    async def recycle_session(self, session_id: str):
        """回收会话（放入清理队列）"""
        await self.cleanup_queue.put(session_id)
        logger.info(f"Session scheduled for cleanup: {session_id}")

    async def _pool_maintainer(self):
        """后台任务：维持会话池大小"""
        while self.running:
            try:
                current_size = self.queue.qsize()
                if current_size < self.target_pool_size:
                    needed = self.target_pool_size - current_size
                    logger.info(f"Pool low ({current_size}/{self.target_pool_size}), replenishing...")
                    
                    # 并发创建会话
                    tasks = []
                    for _ in range(needed):
                        tasks.append(self.client.create_chat_session())
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    async with self._pool_lock:
                        for res in results:
                            if isinstance(res, str) and not isinstance(res, Exception):
                                await self.queue.put(res)
                            else:
                                logger.error(f"Failed to create background session: {res}")
                                
                    logger.info(f"Pool replenished. Current size: {self.queue.qsize()}")
                
                await asyncio.sleep(2)  # 每2秒检查一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in pool maintainer: {e}")
                await asyncio.sleep(5)

    async def _cleanup_worker(self):
        """后台任务：清理废弃会话"""
        while self.running:
            try:
                session_id = await self.cleanup_queue.get()
                try:
                    await self.client.delete_chat_session(session_id)
                    logger.info(f"Background cleanup success: {session_id}")
                except Exception as e:
                    logger.error(f"Background cleanup failed for {session_id}: {e}")
                finally:
                    self.cleanup_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup worker: {e}")
