"""External source clients: no @testable imports or Kotlin friend paths."""
import argparse
import os
from pathlib import Path
import re
from verification.managed_tools import capture, write_report

PROBES = ('constructor','owner','session','mutation')


def expected_diagnostic(platform, probe, output):
    text = output.lower()
    if platform == 'swift':
        if probe == 'constructor': return 'refreshrequest' in text and any(p in text for p in ('initializer is inaccessible','cannot be constructed','no accessible initializers','inaccessible due to'))
        if probe == 'mutation': return 'requestid' in text and any(p in text for p in ('cannot assign','get-only','let constant'))
        return probe in text and any(p in text for p in ('inaccessible due to','has no member'))
    if probe == 'constructor': return 'refreshrequest' in text and any(p in text for p in ('cannot access','private','internal'))
    if probe == 'mutation': return 'val cannot be reassigned' in text or ('requestid' in text and ('cannot be reassigned' in text or 'cannot access' in text))
    return probe in text and ('cannot access' in text or 'unresolved reference' in text)


def swift_artifacts(root):
    """Find public modules/objects for SwiftPM native or Xcode build backends."""
    debug = Path(root)/'ios/.build/debug'
    targets = ('NativeContract','AsyncNativeContract')
    modules = debug/'Modules'
    groups = [sorted((debug/f'{name}.build').glob('*.swift.o')) for name in targets]
    if all((modules/f'{name}.swiftmodule').exists() for name in targets) and all(groups):
        return modules, [obj for group in groups for obj in group]
    objects = [debug/f'{name}.o' for name in targets]
    if all((debug/f'{name}.swiftmodule').exists() for name in targets) and all(obj.is_file() for obj in objects):
        return debug, objects
    return None


def run(root, out, platform):
    root,out = Path(root),Path(out); out.mkdir(parents=True,exist_ok=True)
    fixtures = root/'verification/managed-api'/platform
    source = root/('ios/Sources/AsyncNativeContract/ManagedAsyncSession.swift' if platform == 'swift' else 'android/async-library/src/main/kotlin/nativecontract/async/ManagedAsyncSession.kt')
    if not source.is_file(): return write_report(out,'api-report.json',{'verdict':'NOT_RUN','reason':'managed facade source unavailable','platform':platform})
    if platform == 'swift':
        artifacts = swift_artifacts(root)
        if artifacts is None:
            return write_report(out,'api-report.json',{'verdict':'NOT_RUN','reason':'built public module unavailable','platform':platform})
        modules, objects = artifacts
        positive = ['swiftc','-swift-version','6','-parse-as-library','-module-name','ExternalManagedProbe','-I',str(modules),str(fixtures/'positive.swift'),*[str(o) for o in objects],'-o',str(out/'positive')]
        runtime = [str(out/'positive')]
        negative = lambda probe: ['swiftc','-swift-version','6','-typecheck','-module-name','ExternalManagedProbe','-I',str(modules),str(fixtures/f'{probe}.swift')]
    else:
        libs = root/'android/async-library/build/install/async-library/lib'; jars = sorted(libs.glob('*.jar'))
        cache = Path(os.environ.get('GRADLE_USER_HOME',str(root/'.gradle-home')))/'caches/modules-2/files-2.1'
        compiler = list((cache/'org.jetbrains.kotlin/kotlin-compiler-embeddable/2.3.20').glob('**/*.jar'))
        if not jars or not compiler:
            return write_report(out,'api-report.json',{'verdict':'NOT_RUN','reason':'installed module or pinned Kotlin compiler unavailable','platform':platform})
        compiler_cp = os.pathsep.join(str(p) for p in sorted(cache.glob('**/*.jar')))
        libs_cp = os.pathsep.join(str(p) for p in jars)
        prefix = ['java','-cp',compiler_cp,'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-module-name','managed_external_probe','-classpath',libs_cp]
        positive = prefix+[str(fixtures/'positive.kt'),'-d',str(out/'positive.jar')]
        runtime = ['java','-cp',str(out/'positive.jar')+os.pathsep+libs_cp,'PositiveKt']
        negative = lambda probe: prefix+[str(fixtures/f'{probe}.kt'),'-d',str(out/f'{probe}.jar')]
    evidence = {}
    evidence['positive-compile'] = capture(positive,out,'positive-compile',cwd=root)
    if evidence['positive-compile']['exitCode'] != 0:
        return write_report(out,'api-report.json',{'verdict':'INFRA_FAILURE','reason':'positive external client did not compile','platform':platform,'commands':evidence})
    evidence['positive-run'] = capture(runtime,out,'positive-run',cwd=root)
    if evidence['positive-run']['exitCode'] != 0:
        return write_report(out,'api-report.json',{'verdict':'INFRA_FAILURE','reason':'positive token reuse/immutability failed','platform':platform,'commands':evidence})
    statuses = []
    for probe in PROBES:
        record = capture(negative(probe),out,probe,cwd=root); evidence[probe] = record
        output = (out/f'{probe}.stdout.log').read_text(errors='replace')+(out/f'{probe}.stderr.log').read_text(errors='replace')
        if record['exitCode'] == 0: status = 'SEMANTIC_FAIL'
        elif record['exitCode'] is None or record['timedOut'] or record['exitCode'] < 0 or not expected_diagnostic(platform,probe,output): status = 'INFRA_FAILURE'
        else: status = 'PASS'
        statuses.append(status)
    verdict = 'INFRA_FAILURE' if 'INFRA_FAILURE' in statuses else 'SEMANTIC_FAIL' if 'SEMANTIC_FAIL' in statuses else 'PASS'
    return write_report(out,'api-report.json',{'verdict':verdict,'platform':platform,'probes':dict(zip(PROBES,statuses)),'commands':evidence})


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));parser.add_argument('--output',required=True);parser.add_argument('--platform',choices=('swift','kotlin'),required=True)
    args = parser.parse_args(); result = run(args.root,args.output,args.platform);print(result['verdict']);return 0 if result['verdict']=='PASS' else 2

if __name__ == '__main__': raise SystemExit(main())
