pipeline {
    agent any
    environment {
        IMAGE_NAME = "suchokrates1/retrievershop-suite"
        TAG = "latest"
    }
    stages {
        stage('Checkout') {
            steps {
                // Pobiera repo (jeśli korzystasz z "Pipeline script from SCM" — ten krok można pominąć)
                git url: 'https://github.com/suchokrates1/retrievershop-suite'
            }
        }
        stage('Build Docker image') {
            steps {
                script {
                    docker.build("${IMAGE_NAME}:${TAG}")
                }
            }
        }
        // stage('Push to Docker Hub') {
        //     steps {
        //         withDockerRegistry([ credentialsId: 'dockerhub', url: '' ]) {
        //             docker.image("${IMAGE_NAME}:${TAG}").push()
        //         }
        //     }
        // }
    }
}
