from app.schemas.llm_usage import LLMUsage

class CostCalculator:
    PRICING = {
        "gpt-5.6-luna": {
            "input": 0.20,
            "cached_input": 0.02,
            "output": 1.20,
        },
    }
    
    def calculate(self, usage: LLMUsage):
        pricing = self.PRICING[usage.model]
        
        uncached_input_tokens = usage.input_tokens - usage.cached_input_tokens
        
        input_token_cost = (uncached_input_tokens/1000000) * pricing['input']
        
        cached_input_token_cost = (usage.cached_input_tokens/1000000) * pricing["cached_input"]
        
        output_token_cost = (usage.output_tokens/1000000) * pricing["output"]
        
        total_cost = input_token_cost+cached_input_token_cost+output_token_cost
        
        return {
            "model": usage.model,
            "input_cost": input_token_cost,
            "cached_input_cost": cached_input_token_cost,
            "output_cost": output_token_cost,
            "total_cost": total_cost
        }