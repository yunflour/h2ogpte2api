"""配置管理模块"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """应用配置类"""
    
    # h2ogpte 配置
    H2OGPTE_BASE_URL: str = os.getenv("H2OGPTE_BASE_URL", "https://h2ogpte.genai.h2o.ai")
    
    # Guest 模式（自动获取和刷新凭证）
    IS_GUEST: bool = os.getenv("IS_GUEST", "true").lower() in ("true", "1", "yes")
    
    # 静态凭证（非 Guest 模式使用）
    _H2OGPTE_SESSION: str = os.getenv("H2OGPTE_SESSION", "")
    _H2OGPTE_CSRF_TOKEN: str = os.getenv("H2OGPTE_CSRF_TOKEN", "")
    
    # 默认为 h2ogpte-guest，登录用户需要设置为 workspaces/<uuid>
    H2OGPTE_WORKSPACE_ID: str = os.getenv("H2OGPTE_WORKSPACE_ID", "workspaces/h2ogpte-guest")
    # 自定义 Prompt Template ID（留空则不使用，填写 UUID 如：37b22dcd-a3c7-406c-8890-387ea6668513）
    H2OGPTE_PROMPT_TEMPLATE_ID: str = os.getenv("H2OGPTE_PROMPT_TEMPLATE_ID", "")
    
    # 服务器配置
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "2156"))
    
    # API Key 验证（留空则不验证）
    API_KEY: str = os.getenv("API_KEY", "")
    
    # 动态凭证（运行时更新）
    _current_session: str = ""
    _current_csrf_token: str = ""
    
    @classmethod
    def get_session(cls) -> str:
        """获取当前 session"""
        if cls.IS_GUEST:
            # Guest 模式使用动态凭证
            if cls._current_session:
                return cls._current_session
            # 尝试从存储加载
            from credential_store import credential_store
            return credential_store.get_session()
        else:
            return cls._H2OGPTE_SESSION
    
    @classmethod
    def get_csrf_token(cls) -> str:
        """获取当前 CSRF token"""
        if cls.IS_GUEST:
            if cls._current_csrf_token:
                return cls._current_csrf_token
            from credential_store import credential_store
            return credential_store.get_csrf_token()
        else:
            return cls._H2OGPTE_CSRF_TOKEN
    
    @classmethod
    def update_credentials(cls, session: str, csrf_token: str):
        """更新凭证（用于 401 后刷新）"""
        cls._current_session = session
        cls._current_csrf_token = csrf_token
    
    @classmethod
    def get_cookies(cls) -> dict:
        """获取请求所需的 cookies"""
        return {
            "h2ogpte.session": cls.get_session()
        }
    
    @classmethod
    def get_headers(cls) -> dict:
        """获取请求所需的 headers"""
        return {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": cls.H2OGPTE_BASE_URL,
            "x-csrf-token": cls.get_csrf_token(),
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }


config = Config()
