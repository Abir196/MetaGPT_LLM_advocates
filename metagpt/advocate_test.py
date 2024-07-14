import asyncio
import platform
from typing import List, Tuple
from metagpt.actions import Action
from metagpt.logs import logger
from metagpt.roles import Role
from metagpt.schema import Message
from metagpt.team import Team

# Global variables for debate content
QUESTION = "Should AI be regulated?"
ANSWER1 = "Yes, it should"
ANSWER2 = "No, no need for regulation"

class DefendAnswer(Action):
    PROMPT_TEMPLATE: str = """
    You're an eloquent advocate defending this answer: {answer} to the question: {question}. Your opponent
    defends: {opponent_answer}. Convince the audience your argument is better. Use the latest feedback and your opponent's last argument to improve your case.
    Latest feedback: {feedback}
    Opponent's last argument: {opponent_argument}
    Respond in under 80 words.
    Your defense:
    """
    name: str = "DefendAnswer"

    async def run(self, question: str, answer: str, opponent_answer: str, opponent_argument: str = "", feedback: str = ""):
        prompt = self.PROMPT_TEMPLATE.format(question=question, answer=answer, opponent_answer=opponent_answer, 
                                             opponent_argument=opponent_argument, feedback=feedback)
        return await self._aask(prompt)

class JudgeAnswer(Action):
    PROMPT_TEMPLATE: str = """
    You're a fair, impartial judge in a debate on: "{question}". Answer 1: "{answer1}". Answer 2: "{answer2}".
    Your goal is to provide feedback that will help advocates improve and differentiate their arguments more clearly.
    Current round: {current_round}
    Total rounds: {total_rounds}
    Previous scores: {previous_scores}
    
    Defense for 1st answer: {defense1}
    Defense for 2nd answer: {defense2} 
    
    Provide specific, constructive feedback to help each advocate strengthen their unique position. 
    Encourage them to address weaknesses and highlight distinctions.
    Aim for your feedback to lead to more divergent scores in future rounds.
    
    Give your feedback in under 50 words:
    """
    name: str = "JudgeAnswer"

    async def run(self, question: str, answer1: str, answer2: str, defense1: str, defense2: str, current_round: int, total_rounds: int, previous_scores: list):
        prompt = self.PROMPT_TEMPLATE.format(
            question=question, answer1=answer1, answer2=answer2, defense1=defense1, defense2=defense2,
            current_round=current_round, total_rounds=total_rounds, previous_scores=previous_scores
        )
        return await self._aask(prompt)

class ScoreAnswer(Action):
    PROMPT_TEMPLATE: str = """
    You're a fair, impartial judge scoring a debate on: "{question}". Answer 1: "{answer1}". Answer 2: "{answer2}".
    Current round: {current_round}
    Total rounds: {total_rounds}
    Previous scores: {previous_scores}
    
    Last defense for 1st answer: {defense1}
    Last defense for 2nd answer: {defense2} 
    
    Score each answer between 1 and 20. The stronger argument should get a score closer to 20, the weaker closer to 1.
    Aim for a greater score difference than in previous rounds, unless one side is clearly dominant.
    
    Return only the score tuple (score1, score2). Example: (18, 9)
    Your scores:
    """
    name: str = "ScoreAnswer"

    async def run(self, question: str, answer1: str, answer2: str, defense1: str, defense2: str, current_round: int, total_rounds: int, previous_scores: list):
        prompt = self.PROMPT_TEMPLATE.format(
            question=question, answer1=answer1, answer2=answer2, defense1=defense1, defense2=defense2,
            current_round=current_round, total_rounds=total_rounds, previous_scores=previous_scores
        )
        return await self._aask(prompt)

class Advocate(Role):
    def __init__(self, name: str, answer: str, opponent_answer: str, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.answer = answer
        self.opponent_answer = opponent_answer
        self.defend_action = DefendAnswer()
        self.set_actions([self.defend_action])
        self._watch([DefendAnswer])

    async def _act(self) -> Message:
        logger.info(f"{self.name}: Preparing argument")
        memories = self.rc.memory.get_by_role(role=self.name)
        opponent_memories = self.rc.memory.get_by_role(role=f"Opponent of {self.name}")
        
        opponent_argument = opponent_memories[-1].content if opponent_memories else ""
        feedback = self.rc.memory.get_by_role(role="Judge")[-1].content if self.rc.memory.get_by_role(role="Judge") else ""

        new_defense = await self.defend_action.run(question=QUESTION, answer=self.answer, opponent_answer=self.opponent_answer,
                                     opponent_argument=opponent_argument, feedback=feedback)

        msg = Message(content=new_defense, role=self.name, cause_by=DefendAnswer)
        self.rc.memory.add(msg)
        return msg

class Judge(Role):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "Judge"
        self.judge_action = JudgeAnswer()
        self.set_actions([self.judge_action])
        self._watch([DefendAnswer])

    async def _act(self, current_round: int, total_rounds: int, previous_scores: list) -> Message:
        logger.info("Judge: Evaluating arguments")
        memories = self.rc.memory.get(k=2)
        if len(memories) < 2:
            return Message(content="Waiting for more arguments.", role=self.name)

        advocate1_arg = memories[-2].content
        advocate2_arg = memories[-1].content

        evaluation = await self.judge_action.run(question=QUESTION, answer1=ANSWER1, answer2=ANSWER2, 
                                                 defense1=advocate1_arg, defense2=advocate2_arg,
                                                 current_round=current_round, total_rounds=total_rounds, 
                                                 previous_scores=previous_scores)

        msg = Message(content=evaluation, role=self.name)
        self.rc.memory.add(msg)
        return msg

class Scorer(Role):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "Scorer"
        self.score_action = ScoreAnswer()
        self.set_actions([self.score_action])
        self._watch([DefendAnswer])

    async def _act(self, current_round: int, total_rounds: int, previous_scores: list) -> Message:
        logger.info("Scorer: Scoring arguments")
        memories = self.rc.memory.get(k=2)
        if len(memories) < 2:
            return Message(content="Waiting for more arguments.", role=self.name)

        advocate1_arg = memories[-2].content
        advocate2_arg = memories[-1].content

        scores = await self.score_action.run(question=QUESTION, answer1=ANSWER1, answer2=ANSWER2, 
                                             defense1=advocate1_arg, defense2=advocate2_arg,
                                             current_round=current_round, total_rounds=total_rounds, 
                                             previous_scores=previous_scores)

        msg = Message(content=scores, role=self.name)
        self.rc.memory.add(msg)
        return msg

async def debate(investment: float = 3.0, n_round: int = 5) -> List[str]:
    advocate1 = Advocate(name="Advocate1", answer=ANSWER1, opponent_answer=ANSWER2)
    advocate2 = Advocate(name="Advocate2", answer=ANSWER2, opponent_answer=ANSWER1)
    judge = Judge()
    scorer = Scorer()
    
    print(f"Debate Question: {QUESTION}")
    print(f"Advocate1 defends: {ANSWER1}")
    print(f"Advocate2 defends: {ANSWER2}\n")

    initial_msg = Message(content=QUESTION, role="Human", cause_by=DefendAnswer)
    advocate1.rc.memory.add(initial_msg)

    previous_scores = []
    scores = []

    for i in range(n_round):
        print(f"Round {i+1}:")
        
        msg1 = await advocate1._act()
        advocate2.rc.memory.add(Message(content=msg1.content, role="Opponent of Advocate2", cause_by=DefendAnswer))
        judge.rc.memory.add(msg1)
        scorer.rc.memory.add(msg1)
        print(f"Advocate1: {msg1.content}")

        msg2 = await advocate2._act()
        advocate1.rc.memory.add(Message(content=msg2.content, role="Opponent of Advocate1", cause_by=DefendAnswer))
        judge.rc.memory.add(msg2)
        scorer.rc.memory.add(msg2)
        print(f"Advocate2: {msg2.content}")

        judge_msg = await judge._act(current_round=i+1, total_rounds=n_round, previous_scores=previous_scores)
        advocate1.rc.memory.add(judge_msg)
        advocate2.rc.memory.add(judge_msg)
        print(f"Judge: {judge_msg.content}")

        score_msg = await scorer._act(current_round=i+1, total_rounds=n_round, previous_scores=previous_scores)
        print(f"Scorer: {score_msg.content}")
        scores.append(score_msg.content)
        
        # Parse and store the new scores
        new_scores = eval(score_msg.content)
        previous_scores.append(new_scores)
        
        print()  # Add a blank line between rounds

    # Print final scores
    print("Final Scores:")
    for round_num, (score1, score2) in enumerate(previous_scores, 1):
        print(f"Round {round_num}: Advocate1 - {score1}, Advocate2 - {score2}")

    return scores

async def run_debate(investment: float = 0.1, n_round: int = 3) -> List[str]:
    return await debate(investment, n_round)
# # Run the debate
# async def main():
#     scores = await debate(investment=0.1, n_round=3)
#     print("\nReturned Scores:")
#     print(scores)

# # This is the correct way to run asyncio in Colab
# await main()
