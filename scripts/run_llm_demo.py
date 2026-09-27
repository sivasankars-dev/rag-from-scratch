from dotenv import load_dotenv
from app.services.llm_service import LLMService
load_dotenv()

def main():
    llm = LLMService()
    
    result = llm.generate("Explain what an API is in one simple sentence.")
    
    print(result)
    
if __name__ == "__main__":
    main()