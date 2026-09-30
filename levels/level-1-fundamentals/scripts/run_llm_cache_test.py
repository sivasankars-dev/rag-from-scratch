from dotenv import load_dotenv

from services.llm_service import LLMService


load_dotenv()


def main():
    llm = LLMService()

    long_context = """
    Company Policy Document

    Annual Leave:
    Employees are entitled to 20 days of annual leave per year.

    Sick Leave:
    Employees are entitled to sick leave according to company policy.

    Parental Leave:
    Employees may take parental leave according to company policy.

    Carry Forward:
    Employees can carry forward unused annual leave up to a maximum of 10 days.

    Work From Home:
    Employees may work from home according to the company's remote work policy.
    """ * 20

    prompt = f"""
    Use the following company policy context to answer the question.

    Context:
    {long_context}

    Question:
    How many annual leave days do employees get?
    """

    answer = llm.generate(prompt)

    print(answer)


if __name__ == "__main__":
    main()