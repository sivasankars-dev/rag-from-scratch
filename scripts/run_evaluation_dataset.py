from app.services.evaluation_dataset import EvaluationDataset

def main():
    dataset = EvaluationDataset("data/evaluation_dataset.json")

    evaluation_cases = dataset.load()

    print(f"Number of evaluation cases: {len(evaluation_cases)}")

    for index, case in enumerate(evaluation_cases, start=1):
        print("=" * 60)
        print(f"Evaluation Case: {index}")
        print(f"Question: {case['question']}")
        print(f"Expected Answer: {case['expected_answer']}")
        print(f"Expected Source: {case['expected_source']}")
        print(f"Expected Chunk: {case['expected_chunk']}")
    

if __name__ == "__main__":
    main()