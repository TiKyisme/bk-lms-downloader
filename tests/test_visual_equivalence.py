import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location("visual_equivalence",Path("tools")/"analyze_visual_equivalence.py")
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

def test_identical_and_inserted_sequences():
    assert module.align([1,2,3],[1,2,3]) == ([(1,1,0),(2,2,0),(3,3,0)],[],[])
    aligned,left,right=module.align([1,2,9,3],[1,2,3]); assert len(aligned)==3 and left==[3] and right==[]

def test_deleted_multiple_changed_and_reordered_sequences_are_conservative():
    assert module.align([1,2,3],[1,3])[1:]==([2],[])
    assert module.align([1,8,9,2,3],[1,2,3])[1]==[2,3]
    assert module.align([1,2,3],[1,(1<<64)-1,3])[1:]==([2],[2])
    aligned,left,right=module.align([0,0xFFFF,0xFFFF0000],[0xFFFF0000,0xFFFF,0]); assert len(aligned)<3 or left or right
