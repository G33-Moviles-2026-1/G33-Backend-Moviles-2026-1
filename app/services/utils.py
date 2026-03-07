from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["bcrypt"], 
    deprecated="auto",
    truncate_error=True 
)

def get_hash(string: str) -> str:
    return pwd_context.hash(string)

def compare_hash(str: str, strhashed: str) -> bool:
    return pwd_context.verify(str, strhashed)