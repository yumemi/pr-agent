from fastapi import FastAPI
from mangum import Mangum
from starlette.middleware import Middleware
from starlette_context.middleware import RawContextMiddleware
import boto3
import json
import os
import base64
from typing import Dict, Optional

# シークレットキーと環境変数名のマッピング
SECRET_ENV_MAPPING = {
    'openai_key': 'DYNACONF_OPENAI__KEY',
    'github_app_id': 'DYNACONF_GITHUB__APP_ID',
    'github_webhook_secret': 'DYNACONF_GITHUB__WEBHOOK_SECRET',
    'github_private_key': 'DYNACONF_GITHUB__PRIVATE_KEY',
}

class SecretLoadError(Exception):
    """シークレットの読み込みに失敗した場合のカスタム例外"""
    pass

def load_secrets() -> Optional[Dict[str, str]]:
    """
    Load secrets from AWS Secrets Manager and set them as environment variables.
    
    Returns:
        Dict[str, str]: 設定された環境変数のマップ
        
    Raises:
        SecretLoadError: 必須シークレットの取得に失敗した場合
    """
    try:
        secret_name = os.environ.get('SECRETS_NAME')
        if not secret_name:
            raise SecretLoadError("SECRETS_NAME environment variable is not set")
            
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager'
        )
        
        response = client.get_secret_value(SecretId=secret_name)
        if not response.get('SecretString'):
            raise SecretLoadError(f"No secret string found in secret: {secret_name}")
            
        secrets = json.loads(response['SecretString'])
        missing_secrets = [
            secret_key for secret_key in SECRET_ENV_MAPPING.keys()
            if secret_key not in secrets
        ]
        
        if missing_secrets:
            raise SecretLoadError(
                f"Required secrets are missing: {', '.join(missing_secrets)}"
            )
            
        # すべてのシークレットが存在することを確認した後で環境変数に設定
        for secret_key, env_var in SECRET_ENV_MAPPING.items():
            value = secrets[secret_key]
            # GitHub Private Keyの場合、base64デコード
            if secret_key == 'github_private_key':
                try:
                    value = base64.b64decode(value).decode('utf-8')
                except Exception as e:
                    raise SecretLoadError(f"Failed to decode base64 private key: {str(e)}")
            os.environ[env_var] = str(value)
            
        return {env_var: os.environ[env_var] for env_var in SECRET_ENV_MAPPING.values()}
            
    except SecretLoadError:
        raise  # SecretLoadErrorはそのまま再送出
    except Exception as e:
        raise SecretLoadError(f"Failed to load secrets: {str(e)}") from e

try:
    # モジュールの初期化時にシークレットを読み込む
    load_secrets()
except SecretLoadError as e:
    print(f"Critical error loading secrets: {str(e)}")
    raise  # アプリケーションの起動を中止

# FastAPIアプリケーションの初期化
middleware = [Middleware(RawContextMiddleware)]
app = FastAPI(middleware=middleware)

# シークレットが環境変数に設定された後でrouterをインポート
from pr_agent.servers.github_app import router
app.include_router(router)

# Mangumハンドラーの初期化
handler = Mangum(app, lifespan="off")

def serverless(event, context):
    return handler(event, context)
