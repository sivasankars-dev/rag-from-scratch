from app.services.cost_calculator import CostCalculator

def main():
    calculator = CostCalculator()
    
    result = calculator.calculate(
        model="gpt-5.6-luna",
        input_tokens=1957,
        cached_input_tokens=1954,
        output_tokens=18,
    )

    print(result)
    
if __name__ == "__main__":
    main()
    