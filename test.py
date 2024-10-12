import shutil
from pathlib import Path
import logging
from lib.utils import (
    create_logger,
    load_problem_from_folder,
    verify_code_syntax,
    extract_text,
    maybe_remove_backticks,
    save_to_disk,
)
from lib.llms import LLM
from lib.prompts import (
    REFLECTION_INSTRUCTIONS_USER,
    REFLECTION_INSTRUCTIONS_SYSTEM,
    initial_advisor_prompt,
    extract_prompt,
    CODER_INSTRUCTIONS,
    manager_prompt,
    prompt_rephrase_problem,
    SOLVER_INSTRUCTIONS,
    OUTPUT_FORMAT_CLASSIFIER,
)
from solution import SolutionManager, Solution


def output_format_indicator(problem, logger):
    """
    Determines whether the problem requires an exact output format match or not.
    """
    llm = LLM('gpt4', logger=logger)
    messages = [
        {
            'role': 'user',
            'content': OUTPUT_FORMAT_CLASSIFIER.format(problem=problem.problem_description)
        },
    ]
    out = llm.run_messages(messages=messages, temperature=0.0)
    logger.info(f"{problem.problem_name} requires exact output format? {out}\n")
    return out

class Trainer:
    def __init__(self, model_name, problem):
        self.problem = problem
        self.model_name = model_name

        self.logger = create_logger(f'logs/{problem.problem_name}_{model_name}.log', '{problem.problem_name}_{model_name}')
        self.llm = LLM(model_name=model_name, logger=self.logger)
        self.messages = []
        self.reflection_step = 0
        self.solution_list=[]
        self.sm = SolutionManager()

    @property
    def method_dict(self):
        return {
            "solve_problem_pro":self.solve_problem_pro,
            "reflection_pro":self.reflection_pro,
            "chain_of_thoughts":self.chain_of_thoughts,
            "interpreter":self.interpreter,
            "meta_learning":self.meta_learning,
        }
    def run(self, method):
        return self.method_dict[method]()
    
    def run(self, method):
        try:
            m = self.method_dict()[method]
            m()
        except:
            raise ValueError("method name error")
    
    def battle_ground(self):
        
        solution_list = []

        #'Subsonic Subway'
        #prompt1 = """You are Competitor #1. Your goal is to provide the TRULY correct and NO-TIMEOUT solution. You NEVER agree with Competitor#2. You always provide the missing or misunderstood points by Competitor#2 and provide argument from the facts or derivations based on the input information. \n <root><problem_statement>{problem}</problem_statement></root>"""
        #prompt2 = """You are Competitor #2: Your goal is to provide the TRULY correct and NO-TIMEOUT solution. You MAY learn from Competitor#1 but you always provide argument from the facts or derivations based on the input information. \n <root><problem_statement>{problem}</problem_statement></root>"""
        
        #'Prime Subtractorization'
        prompt1 = """You are Competitor #1: Your goal is to provide the TRULY correct and NO-TIMEOUT solution. You NEVER agree with Competitor#2. You always provide argument from the facts or derivations based on the input information, and explicitly illustrate your NEW approach, fix and technique.\n <root><problem_statement>{problem}</problem_statement></root>"""
        prompt2 = """You are Competitor #2. Your goal is to provide the TRULY correct and NO-TIMEOUT solution. You NEVER agree with Competitor#1. You always provide the overlook insights from the problem, provide NEW approach, provide fix and advanced techniques. \n <root><problem_statement>{problem}</problem_statement></root>"""
        
        #prompt1 = """You are Competitor #1: Your goal is to provide the TRULY correct and NO-TIMEOUT solution. You NEVER agree with Competitor#1. You always provide argument from the facts or derivations based on the input information, and explicitly illustrate your NEW approach, fix and technique.\n <root><problem_statement>{problem}</problem_statement></root>"""
        #prompt2 = """You are Competitor #2. Your goal is to provide the TRULY correct and NO-TIMEOUT solution. You NEVER agree with Competitor#1. You may take a step back to think through the problem again. You always provide the missing KEY technique or misunderstood points by Competitor#1, and explicitly illustrate your NEW approach, fix and technique. \n <root><problem_statement>{problem}</problem_statement></root>"""
        
        prompt1 = prompt1.format(problem=self.problem.problem_description)
        prompt2 = prompt2.format(problem=self.problem.problem_description)

        prompts = [prompt1, prompt2]
        messages1 = [{
                'role': 'user',
                'content': prompt1
            },
            {
                'role': 'assistant',
                'content': "understood."
            },
            ]
        messages2 = [{
                'role': 'user',
                'content': prompt2
            },
            {
                'role': 'assistant',
                'content': "understood."
            },
            ]
        messages = [messages1, messages2]

        step = 0
        id1, id2 = 1, 2
        while step < 7:
            step += 1
            self.logger.info(f"\n\n***************Step {step}: Competitor {id1} is running...***************\n\n")

            messages[id1-1].append(
                {
                    'role': 'user',
                    'content': prompts[id1-1]
                },
            )
            self.logger.info(f"Competitor#{id1} LLM Input: {prompts[id1-1]}")
            
            out = self.llm.run_messages(messages=messages[id1-1], temperature=1)
            code = self.worker(out)
            self.logger.info(f"Step {step}: Competitor {id1}'s output is {out}")

            s = Solution(code, self.problem.problem_name, self.problem.sample_input_path, self.problem.sample_output_path, self.problem.full_input_path, self.model_name)
            testreport, fullreport = s.eval()
            self.sm.add_solution(s)

            if fullreport and testreport:
                self.logger.info(f"Step {step}: Competitor #{id1}'s testreport is {testreport.content} \n Full test report: {fullreport.content}\n")
            solution_list.append(s)
            
            messages[id1-1].append(
                {
                    'role': 'assistant',
                    'content': out
                },
            )
            
            prompts[id2-1] = f"##Competitor #{id1} provided this <competitor_{id1}_solution>{code}</competitor_{id1}_solution>\n ##The Evaluation Results of Competitor #{id1}'s solution:\n <sample_test>{testreport}</sample_test> <full_test>{fullreport}</full_test>"
            
            id1,id2 = id2,id1

        return solution_list
    
    def interpreter(self):
        """
        Prompt = "Rephrases the problem description for clearer understanding."
        """
        messages = [
            {
                'role': 'user',
                'content': prompt_rephrase_problem.format(problem=self.problem.problem_description)
            },
        ]
        out = self.llm.run_messages(messages=messages, temperature=0)
        self.logger.info(f"Rephraser output: {out}")
        self.problem.problem_description = out
        return out

    def meta_learning(self):
        """
        Preloads historical problem and solution messages for context.
        """
        problem_dir = "dataset/2023/practice/"
        problem_list = [
            "cheeseburger_corollary_ch1.md",
            "cheeseburger_corollary_ch2.md",
            "dim_sum_delivery.md",
            "two_apples_a_day.md",
            "road_to_nutella.md"
        ]
        for problem in problem_list:
            self.preload_messages.extend([
                {
                    'role': 'user',
                    'content': 'You are a world-class coding competitor solving complex problems. I will give you a problem statement, and you analyze the problem and provide a solution.',
                },
                {
                    'role': 'assistant',
                    'content': 'Understood.',
                },
                {
                    'role': 'user',
                    'content': Path(problem_dir + problem).read_text(),
                },
                {
                    'role': 'assistant',
                    'content': Path(problem_dir + problem[:-3] + '_sol.md').read_text(),
                },
            ])
        self.messages = self.preload_messages
        return self.preload_messages

    def reflection_pro(self,):
        """
        Reflects on the solution based on test reports and provides improvements.
        """
        solution_list = []

        code = self.solve_problem_pro()[0].code
        
        while self.reflection_step < 3:
            s = Solution(code, self.problem.problem_name, self.problem.sample_input_path, self.problem.sample_output_path, self.problem.full_input_path, self.model_name)
            testreport, full_testreport = s.eval()
            solution_list.append(s)
            
            self.messages.append(
                {
                    'role': 'user',
                    'content': REFLECTION_INSTRUCTIONS_USER.format(
                        incorrect_solution="[check above the solution and see the below report for reflection]",
                        test_report=testreport.content + "##FULL evaluation results:\n"+ full_testreport.content,
                    )
                })
            out = self.llm.run_messages(messages=self.messages)
            self.logger.info(f"Reflection output: {out}")
            self.messages.append(
                {
                    'role': 'assistant',
                    'content': out
                })
            
            self.reflection_step += 1
            code = self.worker(out)     
            if code:
                s = Solution(code, self.problem.problem_name, self.problem.sample_input_path, self.problem.sample_output_path, self.problem.full_input_path, self.model_name)
                solution_list.append(s)

        return solution_list
    
    def solve_problem_pro(self,):
        """
        Solves the problem using a professional approach.
        """
        self.messages.append({
            'role': 'user',
            'content': self.problem.as_xml,
        })
        out = self.llm.run_messages(messages=self.messages)
        self.messages.append({
            'role': 'assistant',
            'content': out,
        })
        self.logger.info(f"Advisor output: {out}")
 
        code = self.worker(out)
        
        if code:
            s = Solution(code, self.problem.problem_name, self.problem.sample_input_path, self.problem.sample_output_path, self.problem.full_input_path, self.model_name)
        return [s]
    
    def chain_of_thoughts(self):
        """
        Uses a chain-of-thought process to solve the problem.
        """
        messages = []
        question_list = [
            "Carefully read through the problem statement line by line, and rephrase the problem for clearer understanding.\n\n##Problem:\n{problem}\n",
            "List all the key information of this problem for meta-learning: <label>[the keywords of the problem statement, including types of the problem, solution type, algorithms]</label>",
            "Analyze which solution is the most promising. Analyze the time complexity. **If this is a familiar problem, please don't be fooled by experience.** Note: Please be very careful about data contamination. Don't use your memory or knowledge to solve the problem. Read through the problem and provide a correct solution based on your reasoning only.",
            "Pick the best solution and implement the source code with comments on each line of the code."
        ]

        for question in question_list:
            formatted_question = question.format(problem=self.problem.as_xml)
            messages.append({
                'role': 'user',
                'content': formatted_question,
            })
            self.logger.info(formatted_question)
            out = self.llm.run_messages(messages=messages)
            messages.append({
                'role': 'assistant',
                'content': out,
            })
            self.logger.info(f"Assistant output: {out}")

        code = self.worker(out)
        if code:
        
            s = Solution(code, self.problem.problem_name, self.problem.sample_input_path, self.problem.sample_output_path, self.problem.full_input_path, self.model_name)
            testreport, full_testreport = s.eval()
            
        return [s]
    
    def worker(self, assistant_output):
        """
        Processes assistant output to extract and verify the source code.
        """
        messages = [
            {
                'role': 'user',
                'content': CODER_INSTRUCTIONS + f"This is the code: {assistant_output}"
            },
        ]
        out = self.llm.run_messages(messages=messages)
        
        code = extract_text(out, '<source_code>')
        code = maybe_remove_backticks(code)
    
        if verify_code_syntax(code):
            self.logger.info(f"Code syntax correct:\n{code}")
            return code
        else:
            return ""
            #raise ValueError("Source code is not compilable.")

if __name__ == '__main__':
    problem_name = 'Prime Subtractorization'
    #problem_name = 'Subsonic Subway'
    #problem_name = 'Substantial Losses'

    logger = create_logger(f'logs/trainer.log', 'trainer')
    problem = load_problem_from_folder('2024', 'Round1/', problem_name, logger)
    logger.info(f"Solving {problem_name}")

    _ = output_format_indicator(problem, logger)
    
    
    model_name = 'gemini' #ranking powerful to less ['o1', 'gpt4', 'claude', 'gemini', 'gpt3.5'] from most capable to least capable 
    trainer1 = Trainer(model_name, problem,)

    sols = trainer1.battle_ground()
    trainer1.sm.to_submit('to_submit/')
    print(trainer1.sm.solution_manager)


