from sequence_lab.analysis.request import AnalysisRequest, bind_analysis_request
from sequence_lab.compiler.compile import compile_grammar
from sequence_lab.analysis.evidence import compute_evidence
from sequence_lab.analysis.moments import compute_moments, condition_statistics
from sequence_lab.delivery.publish import publish_analysis


def analyze_sequence(db, grammar_ref, cohort_id, member_id, rule_ids=(), *, fault=None):
    request = AnalysisRequest(grammar_ref, cohort_id, member_id, rule_ids)
    bound = bind_analysis_request(db, request)
    plan = compile_grammar(bound.grammar)
    plan.check_binding(bound.grammar)
    evidence = compute_evidence(plan, bound.member.sequence)
    moments = compute_moments(plan, evidence, request.rule_ids)
    result = condition_statistics(moments)
    return publish_analysis(db, bound, result, fault=fault)
