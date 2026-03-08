from __future__ import annotations

DOC_TYPES = {
    "clinical_evaluation_protocol": {
        "label": "Clinical Evaluation Protocol",
        "required_fields": [
            "document_title", "document_number", "version", "date",
            "device_name", "device_model", "intended_purpose",
            "manufacturer_name", "regulatory_framework",
            "evaluation_scope", "literature_search_strategy",
            "inclusion_criteria", "exclusion_criteria",
            "clinical_data_sources", "equivalence_device",
            "benefit_risk_assessment", "conclusions", "author", "reviewer"
        ],
        "optional_fields": [
            "device_classification", "predicate_device",
            "post_market_surveillance_ref", "notified_body", "approval_date",
            "biocompatibility_standard", "biological_endpoints_evaluated",
            "biocompatibility_assessment", "cytotoxicity_result",
            "sensitization_result", "irritation_result"
        ]
    },
    "risk_management_report": {
        "label": "Risk Management Report",
        "required_fields": [
            "document_title", "document_number", "version", "date",
            "device_name", "manufacturer_name", "risk_management_standard",
            "hazard_identification", "risk_estimation", "risk_evaluation",
            "risk_control_measures", "residual_risk_assessment",
            "benefit_risk_ratio", "author", "reviewer"
        ],
        "optional_fields": ["fmea_reference", "fault_tree_ref"]
    },
    "test_protocol": {
        "label": "Test Protocol / Study Design",
        "required_fields": [
            "document_title", "document_number", "version", "date",
            "test_objective", "device_name", "test_standard",
            "sample_size", "acceptance_criteria", "test_environment",
            "test_procedure", "pass_fail_criteria", "author", "reviewer"
        ],
        "optional_fields": ["statistical_method", "deviation_procedure"]
    },
    "design_history_file": {
        "label": "Design History File Entry",
        "required_fields": [
            "document_title", "document_number", "version", "date",
            "device_name", "design_input", "design_output",
            "design_verification", "design_validation",
            "design_review_record", "author"
        ],
        "optional_fields": ["change_control_ref", "risk_ref"]
    },
    "unknown": {
        "label": "Unknown Document",
        "required_fields": ["document_title", "document_number", "version", "date"],
        "optional_fields": []
    }
}

SECTION_KEYWORDS = {
    "document_control": ["document", "title", "version", "revision", "author", "reviewer", "approval", "metadata", "header"],
    "device_information": ["device", "product", "manufacturer", "model", "description", "classification"],
    "regulatory_framework": ["regulatory", "framework", "standard", "compliance", "iso", "mdr", "fda"],
    "evaluation_scope": ["scope", "objective", "purpose", "intended", "evaluation"],
    "evidence_methodology": ["literature", "search", "method", "criteria", "clinical data", "sources", "dataset"],
    "risk_assessment": ["risk", "hazard", "fmea", "control", "residual", "benefit"],
    "conclusion": ["conclusion", "summary", "decision", "recommendation"],
    "other": []
}

SECTION_FIELD_HINTS = {
    "document_control": {"document_title", "document_number", "version", "date", "author", "reviewer"},
    "device_information": {"device_name", "device_model", "manufacturer_name", "device_classification", "predicate_device"},
    "regulatory_framework": {"regulatory_framework", "risk_management_standard", "notified_body", "approval_date"},
    "evaluation_scope": {"intended_purpose", "evaluation_scope", "test_objective", "test_environment"},
    "evidence_methodology": {
        "literature_search_strategy", "inclusion_criteria", "exclusion_criteria", "clinical_data_sources",
        "sample_size", "test_standard", "acceptance_criteria", "test_procedure", "pass_fail_criteria",
        "biocompatibility_standard", "biological_endpoints_evaluated",
        "cytotoxicity_result", "sensitization_result", "irritation_result"
    },
    "risk_assessment": {
        "hazard_identification", "risk_estimation", "risk_evaluation", "risk_control_measures",
        "residual_risk_assessment", "benefit_risk_assessment", "benefit_risk_ratio",
        "biocompatibility_assessment"
    },
    "conclusion": {"conclusions"},
}
